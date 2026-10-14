#!/usr/bin/env python3
"""Dictado continuo por voz: pega lo transcrito en la ventana activa y pulsa Enter tras un silencio."""

import collections
import json
import os
import queue
import re
import sys
import threading
import time
from collections import deque
from pathlib import Path

BASE = Path(__file__).parent
CONFIG_PATH = BASE / "config.json"
PID_PATH = BASE / "dictado.pid"

# ctranslate2 carga las DLL de CUDA con LoadLibrary, que solo mira el PATH:
# add_dll_directory no basta y falla al ejecutar, no al cargar el modelo.
for _sub in ("cublas", "cudnn", "cuda_nvrtc"):
    _dll = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia" / _sub / "bin"
    if _dll.is_dir():
        os.environ["PATH"] = str(_dll) + os.pathsep + os.environ["PATH"]
        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(str(_dll))

import ctypes

import numpy as np
import pyperclip
import sounddevice as sd
from pynput.keyboard import Controller, Key, Listener

import eco
from interruptor import AJUSTES as AJUSTES_INTERRUPTOR, Interruptor


user32 = ctypes.windll.user32


def _titulo(hwnd):
    longitud = user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(longitud + 1)
    user32.GetWindowTextW(hwnd, buffer, longitud + 1)
    return buffer.value


def buscar_ventana(fragmentos):
    """Primera ventana visible cuyo titulo contenga alguno de los fragmentos (minusculas)."""
    encontrada = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def callback(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        titulo = _titulo(hwnd).lower()
        if titulo and any(f in titulo for f in fragmentos):
            encontrada.append(hwnd)
            return False
        return True

    user32.EnumWindows(callback, 0)
    return encontrada[0] if encontrada else None


def enfocar_ventana(hwnd):
    """Fuerza el foco a hwnd saltando la proteccion de Windows contra robo de foco,
    adjuntando temporalmente el hilo de entrada de la ventana activa al nuestro."""
    if not user32.IsWindow(hwnd):
        return False
    actual = user32.GetForegroundWindow()
    if actual == hwnd:
        return True
    # Hay que adjuntar NUESTRO hilo al de la ventana que ahora manda; adjuntar
    # otros dos hilos entre si no levanta la restriccion y SetForegroundWindow
    # devuelve exito sin mover el foco.
    hilo_actual = ctypes.windll.kernel32.GetCurrentThreadId()
    hilo_activo = user32.GetWindowThreadProcessId(actual, None)
    user32.AttachThreadInput(hilo_actual, hilo_activo, True)
    try:
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.SwitchToThisWindow(hwnd, True)
    finally:
        user32.AttachThreadInput(hilo_actual, hilo_activo, False)
    time.sleep(0.05)
    if user32.GetForegroundWindow() == hwnd:
        return True
    # 14-oct: con el navegador del NAS delante el foco no cambiaba ("no se pudo enfocar"):
    # reintento con el truco de la tecla ALT, que Windows cuenta como entrada del usuario
    # 14-oct 18:10: causa real = el aviso emergente de Windows ("Notificación nueva",
    # clase Windows.UI.Core.CoreWindow) se queda con el foco unos segundos y no lo suelta:
    # se le manda cerrar y se reintenta durante ~3 s
    # 14-oct 18:17: ademas quita el bloqueo de robo de foco (timeout 0) y permite a cualquiera
    user32.SystemParametersInfoW(0x2001, 0, 0, 2)  # SPI_SETFOREGROUNDLOCKTIMEOUT = 0
    user32.AllowSetForegroundWindow(0xFFFFFFFF)     # ASFW_ANY
    for intento in range(12):
        fg = user32.GetForegroundWindow()
        if fg and fg != hwnd and "notific" in _titulo(fg).lower():
            user32.PostMessageW(fg, 0x0010, 0, 0)  # WM_CLOSE
            user32.ShowWindow(fg, 6)  # SW_MINIMIZE
        user32.keybd_event(0x12, 0, 0, 0)
        user32.keybd_event(0x12, 0, 2, 0)
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.25)
        if user32.GetForegroundWindow() == hwnd:
            return True
    fg = user32.GetForegroundWindow()
    print(f"  [foco] fallo: en primer plano hwnd={fg} titulo='{_titulo(fg) if fg else ''}'")
    return False

DEFAULTS = {
    "modelo": "large-v3-turbo",
    "idioma": "es",
    "dispositivo": "cuda",
    "segundos_para_enviar": 5.0,
    "segundos_para_transcribir": 0.7,
    # Fin de turno (Smart Turn v3.2, fin_turno.py, 03-oct): si tras esta pausa el audio
    # suena a frase acabada con seguridad >= umbral_turno y el texto no termina en
    # "y/que/de...", se envía ya; si no, se espera a segundos_para_enviar como siempre.
    "fin_turno": True,
    "segundos_turno_acabado": 2.0,
    "umbral_turno": 0.9,
    "microfono": None,
    "enviar_automatico": True,
    "duracion_minima_frase": 0.4,
    "precision": 1,
    "empezar_a_hablar": 0.5,
    "seguir_hablando": 0.28,
    "ventanas_permitidas": ["claude", "cmd", "powershell", "terminal", "windows terminal"],
    # Palabras que Whisper debe favorecer (nombres propios que oye mal) y
    # correcciones seguras aplicadas al texto ya transcrito. Añadir aquí lo que
    # el usuario diga y salga mal escrito.
    # VACÍO a propósito (21-sep): con hotwords, Whisper escribió la propia lista
    # ("Claude, Sonnet, ...") al oír ruido. Si algún día se usa, el filtro
    # de es_alucinacion ya descarta un texto formado solo por estas palabras.
    "palabras_clave": [],
    "palabras_clave_filtro": ["Claude", "Sonnet", "Opus", "Jarvis"],
    # Correcciones seguras al texto ya transcrito: {regex: reemplazo}. Añade las tuyas.
    "correcciones": {},
    **AJUSTES_INTERRUPTOR,
}

SAMPLE_RATE = 16000
BLOQUE = 512  # tamano exacto que espera el detector de voz de Silero
PREROLL_BLOQUES = 32  # ~1 s previo (14-oct: se comía las primeras palabras; antes 16)
# Mientras Jarvis habla su voz no deja silencios, así que la frase se corta a la fuerza
# cada TROZO_CON_JARVIS s para poder transcribirla y decidir si es eco o el usuario.
TROZO_CON_JARVIS = 1.0  # 2,0 tardaba demasiado: "para" llegaba con Jarvis ya callado
SILENCIO_CON_JARVIS = 0.3  # s de silencio que cierran un trozo mientras Jarvis habla
MUESTRAS = Path(__file__).parent / "muestras_voz"  # trozos etiquetados (voz del usuario / eco)
MUESTRAS_MAX = 600
CONTEXTO_HUELLA = 1.0  # s del trozo anterior que se añaden para la huella (total ~2 s)
APRENDER_CADA = 20  # frases nuevas con Jarvis callado entre pasadas de aprendizaje
HUELLA_VETO_CORTE = 0.10  # una orden de corte solo se ignora si la huella es < -0,10
ECO_QUE_ES_USUARIO = 0.15  # dif. el usuario-eco por encima de la cual un 'eco' por texto no se guarda como eco
ENVIO_RUIDO_MIN = 0.45  # parecido al usuario que debe tener lo pegado para el envío pese al ruido
HUELLA_MARGEN = 0.10  # dif. el usuario-eco para darle la razón al usuario (TitaNet 03-oct: el usuario 100 %, eco 1 %)
COLA_ECO = 2.5  # s tras callarse Jarvis en que lo oído aún se compara con su texto
MEMORIA_ECO = 12.0  # s de textos de Jarvis con los que se compara lo oído


class DetectorDeVoz:
    """Silero VAD en streaming, reutilizando el modelo que ya incluye faster-whisper.

    Distingue voz de ruido mucho mejor que medir volumen, que recorta las silabas
    flojas y confunde cualquier golpe con habla.
    """

    CONTEXTO = 64

    def __init__(self):
        import onnxruntime
        from faster_whisper.vad import get_assets_path

        opts = onnxruntime.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        opts.log_severity_level = 4
        self.session = onnxruntime.InferenceSession(
            str(Path(get_assets_path()) / "silero_vad_v6.onnx"),
            providers=["CPUExecutionProvider"],
            sess_options=opts,
        )
        self.reiniciar()

    def reiniciar(self):
        self.h = np.zeros((1, 1, 128), dtype="float32")
        self.c = np.zeros((1, 1, 128), dtype="float32")
        self.contexto = np.zeros((1, self.CONTEXTO), dtype="float32")

    def __call__(self, bloque):
        entrada = np.concatenate([self.contexto, bloque.reshape(1, -1)], axis=1)
        salida, self.h, self.c = self.session.run(
            None, {"input": entrada, "h": self.h, "c": self.c}
        )
        self.contexto = bloque.reshape(1, -1)[:, -self.CONTEXTO :]
        return float(np.ravel(salida)[0])


ALUCINACIONES = (
    "suscribete",
    "suscribanse",
    "gracias por ver",
    "no olvides suscribirte",
    "dale like",
    "hasta la proxima",
    "amara.org",
)


def es_alucinacion(texto):
    limpio = texto.lower().strip(" .,!¡?¿-")
    if not limpio:
        return False
    sin_tildes = (
        limpio.replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
    )
    if any(f in sin_tildes for f in ALUCINACIONES):
        return True
    # Inventos de Whisper con ruido de fondo que solo se descartan si son la frase
    # entera ("Bye." se coló dos veces el 02-oct sin que nadie hablara)
    if re.sub(r"[^a-z ]", "", sin_tildes).strip() in (
            "bye", "bye bye", "byebye", "gracias", "muchas gracias", "gracias gracias",
            "gracias gracias gracias"):
        return True  # "¡Gracias!" suelto con ruido del PC (13-oct-2026)
    # Muletilla de Whisper con ruido: "Subtitulos realizados por la comunidad de
    # Amara.org". Solo se descarta ese patron: una frase real del usuario que hable de
    # subtitulos ("poner subtitulos en italiano") debe pasar (24-sep-2026).
    return bool(re.search(
        r"^subtitulos? (realizados?|por|de la comunidad|en espanol)|^subtitulado por",
        sin_tildes))


def solo_nombres(texto, nombres):
    """True si el texto es solo una lista de 2 o más de esos nombres (Whisper la
    inventa con ruido si conoce palabras clave): 'Claude, Sonnet'."""
    resto = texto.lower()
    hallados = 0
    for n in sorted(nombres, key=len, reverse=True):
        if re.search(r"\b" + re.escape(n.lower()) + r"\b", resto):
            hallados += 1
            resto = re.sub(r"\b" + re.escape(n.lower()) + r"\b", " ", resto)
    return hallados >= 2 and not re.search(r"\w", resto)


def cargar_config():
    if CONFIG_PATH.exists():
        datos = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    else:
        datos = {}
        CONFIG_PATH.write_text(
            json.dumps(DEFAULTS, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    return {**DEFAULTS, **datos}


class Dictado:
    def __init__(self, cfg, simulado=False):
        self.cfg = cfg
        self.simulado = simulado
        self.destino = None
        self.teclado = Controller()
        self.audio = queue.Queue()
        self.trabajos = queue.Queue()
        self.pendientes = 0
        self.lock = threading.Lock()
        self.activo = True
        self.salir = False
        self.hay_texto_sin_enviar = False
        self.texto_dudoso = False
        self.espera_usuario = False  # 07-oct: texto de vídeo/altavoz pegado: no enviar por silencio
        self.umbral = None
        self.ultimo_f10 = 0.0
        self.huellas = None  # voz_usuario.Huellas al primer uso; False si no hay modelo
        self.altavoces = None  # captura de lo que suena por los altavoces (altavoces.py)
        self.aprendiendo = False
        self.nuevas_solo = 0
        self.ultimo_texto = ""  # lo último pegado (para ver si la frase parece acabada)
        self.ultimo_pegado = 0.0  # cuándo se pegó (envío pese al ruido de fondo)
        self.texto_dudoso = False  # lo pegado no suena claramente al usuario: sin envío pese al ruido
        self.detector_turno = None  # fin_turno.FinDeTurno al primer uso; False si falla

    # --- audio ---

    def _callback(self, indata, frames, tiempo, estado):
        if estado:
            print(f"  [audio] {estado}", file=sys.stderr)
        self.audio.put(indata[:, 0].copy())

    # --- transcripcion ---

    def _worker(self, modelo):
        while not self.salir:
            try:
                # dicho = lo que Jarvis decía mientras se grabó este trozo (None si callaba)
                audio, dicho, contexto, fin = self.trabajos.get(timeout=0.3)
            except queue.Empty:
                continue
            try:
                segmentos, _ = modelo.transcribe(
                    audio,
                    language=self.cfg["idioma"],
                    vad_filter=True,
                    beam_size=self.cfg["precision"],
                    hotwords=", ".join(self.cfg["palabras_clave"]) or None,
                    word_timestamps=bool(self.cfg.get("filtro_tramos", False)),
                )
                segmentos = list(segmentos)
                # Con ruido sin voz clara, Whisper inventa muletillas de YouTube
                # ("suscribete al canal", "subtitulos por..."). Se descartan por
                # fiabilidad del segmento y por lista negra.
                utiles = [
                    s.text.strip()
                    for s in segmentos
                    if s.no_speech_prob < 0.6 and s.avg_logprob > -1.0
                ]
                texto = " ".join(utiles).strip()
                bruto = texto
                tramos_quitados = False
                if texto:
                    # 04-oct 19:12: también con Jarvis hablando ("ya lo voy a" de YouTube
                    # pasó como "el usuario por encima" +0,08: con < 8 palabras no se mira la
                    # huella). El loopback lleva la voz de Jarvis Y el vídeo: se quitan los dos
                    texto, sonaba = self._restar_altavoces(modelo, texto, audio, fin)
                    # con el vídeo sonando la huella del usuario sale a medias (mezcla) y lo
                    # suyo se tiraba como "otra persona": lo que queda tras restar el
                    # altavoz no sonaba por él, así que no se pasa por la huella
                    tramos_quitados = sonaba and dicho is None
                if texto and dicho is None:
                    limpio = self._quitar_tramos_ajenos(audio, segmentos)
                    if limpio is not None:
                        texto, tramos_quitados = limpio, True
                for patron, bien in self.cfg["correcciones"].items():
                    texto = re.sub(patron, bien, texto, flags=re.IGNORECASE)
                if es_alucinacion(texto) or solo_nombres(texto, self.cfg["palabras_clave_filtro"]):
                    print(f"  [descartado] \"{texto}\"")
                    texto = ""
                # con Jarvis callado puede hablar cualquiera de la habitación: "solo" y no
                # "usuario" (la huella del usuario se hace solo con muestras revisadas)
                etiqueta = "solo" if dicho is None else "eco"
                if dicho is not None and texto != bruto:
                    etiqueta = "dudoso"  # mezcla de Jarvis y vídeo: no entrena el perfil del eco
                # 05-oct 19:30: "Sí." del usuario dio huella +0,35 (justo en el umbral): con 1-2
                # palabras la huella no es fiable, no se tira por ella
                if texto and dicho is None and not tramos_quitados and len(texto.split()) > 2:
                    ajena, parecido = self._otra_persona(audio)
                    if ajena:
                        print(f"  [otra persona] \"{texto}\" voz {parecido:+.2f}")
                        texto = ""  # se guarda igual como 'solo': el aprendizaje la clasifica
                    elif parecido is None or parecido < ENVIO_RUIDO_MIN:
                        self.texto_dudoso = True
                    else:
                        self.espera_usuario = False  # voz clara del usuario: ya se puede enviar
                elif texto and dicho is None and tramos_quitados:
                    # 04-oct 19:09: con el vídeo sonando no se tira por huella (el usuario mezclado
                    # da poco), pero tampoco se envía solo "pese al ruido": se coló "Es una
                    # nevera." de YouTube porque esta rama nunca marcaba texto_dudoso
                    # 19:13: la huella del vídeo llegó a pasar de 0,45 (vlog con varias
                    # voces): con altavoz sonando nunca hay envío automático pese al ruido
                    # 07-oct 17:40: la captura de altavoces incluye la voz reciente de Claude y
                    # frases normales del usuario quedaban retenidas 20 s: si la huella dice que es
                    # el usuario con claridad (>= ENVIO_RUIDO_MIN) no se retiene
                    parecido_alt = None
                    if len(texto.split()) > 2:
                        try:
                            _aj, parecido_alt = self._otra_persona(audio)
                        except Exception:
                            parecido_alt = None
                    if parecido_alt is not None and parecido_alt >= ENVIO_RUIDO_MIN:
                        self.espera_usuario = False
                    else:
                        self.texto_dudoso = True
                        self.espera_usuario = True
                        print(f"  [dudoso con altavoz] \"{texto[:60]}\": espera al usuario"
                              + (f" (huella {parecido_alt:+.2f})" if parecido_alt is not None else ""))
                if texto and dicho is not None:
                    texto, etiqueta = self._filtrar_eco(texto, dicho, audio, contexto)
                if bruto:
                    self._guardar_muestra(audio, etiqueta, bruto)
                if texto:
                    self._pegar(texto)
            except Exception as exc:
                print(f"  [error transcribiendo] {exc}", file=sys.stderr)
            finally:
                with self.lock:
                    self.pendientes -= 1

    def _localizar_destino(self):
        """Confirma que la ventana fijada sigue existiendo; si no, la vuelve a
        buscar por titulo. Nunca cae en 'escribir donde este el foco'."""
        if self.destino and user32.IsWindow(self.destino):
            return self.destino
        self.destino = buscar_ventana(self.cfg["ventanas_permitidas"])
        if self.destino:
            print(f"  [destino] fijado automaticamente: '{_titulo(self.destino)}'")
        return self.destino

    def fijar_destino_actual(self):
        actual = user32.GetForegroundWindow()
        self.destino = actual
        print(f"  [destino] fijado a mano (F11): '{_titulo(actual)}'")

    def _foco_en_caja_prompt(self, hwnd):
        """05-oct: en la app de escritorio de Claude activar la ventana no basta: el
        cursor se queda donde estuviera (navegador, archivos...) y el texto no entraba
        si el usuario no pinchaba en la caja. Por accesibilidad (UIA) se busca el editor
        "Prompt" (tiptap/ProseMirror) y se le da el foco. Si falla, sigue como antes."""
        try:
            import uiautomation as auto
            with auto.UIAutomationInitializerInThread():
                ventana = auto.ControlFromHandle(hwnd)
                if not ventana or ventana.ClassName != "Chrome_WidgetWin_1":
                    return  # terminal/cmd: no hace falta
                caja = auto.EditControl(searchFromControl=ventana, searchDepth=60,
                                        Compare=lambda c, d: "ProseMirror" in (c.ClassName or ""))
                if caja.Exists(0.3, 0.1):
                    if "ProseMirror-focused" not in (caja.ClassName or ""):
                        caja.SetFocus()
                        time.sleep(0.05)
        except Exception as exc:
            print(f"  [caja prompt] no enfocada: {exc}", file=sys.stderr)

    def _con_foco_en_destino(self, accion):
        """Cambia el foco a la ventana destino, ejecuta `accion` y devuelve el
        foco a donde estaba. Asi el usuario puede dictar sin tocar el raton
        mientras trabaja en otra ventana: la voz siempre llega a Claude Code."""
        destino = self._localizar_destino()
        if not destino:
            print("  [BLOQUEADO] no encuentro ninguna ventana de Claude Code/terminal abierta")
            return False
        origen = user32.GetForegroundWindow()
        cambio = origen != destino
        if cambio and not enfocar_ventana(destino):
            print("  [BLOQUEADO] no se pudo enfocar la ventana destino")
            return False
        if cambio:
            time.sleep(0.08)
        self._foco_en_caja_prompt(destino)
        accion()
        if cambio:
            time.sleep(0.05)
            enfocar_ventana(origen)
        return True

    # --- destino Max (03-oct): el dictado también le habla a Max, el agente local ---
    URL_MAX = "http://127.0.0.1:5001/enviar"
    CAMBIO_DESTINO = re.compile(
        r"^(?:oye |vale |venga )?(?:habla|hablar|hablo|pasa|pasate|cambia|cambio|vamos)\s+"
        r"(?:con|a)\s+(max|claude)[.!?]*$", re.IGNORECASE)

    def _a_max(self):
        return self.cfg.get("destino", "claude") == "max"

    def _cambiar_destino(self, texto):
        """"Habla con Max" / "habla con Claude": cambia a quién va el dictado. Se guarda
        en config.json ("destino") para que sobreviva a un reinicio. True si era eso."""
        m = self.CAMBIO_DESTINO.match(texto.strip())
        if not m:
            return False
        nuevo = m.group(1).lower()
        self.cfg["destino"] = nuevo
        try:
            datos = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            datos["destino"] = nuevo
            CONFIG_PATH.write_text(json.dumps(datos, ensure_ascii=False, indent=4), encoding="utf-8")
        except Exception as exc:
            print(f"  [destino] no guardado en config.json: {exc}", file=sys.stderr)
        self.buffer_max = []
        print(f"  [destino] ahora el dictado va a: {nuevo.upper()}")
        self._pitar(880 if nuevo == "max" else 660, 120)
        return True

    def _enviar_a_max(self):
        import urllib.request

        texto = " ".join(getattr(self, "buffer_max", [])).strip()
        self.buffer_max = []
        if not texto:
            return False
        try:
            pet = urllib.request.Request(
                self.URL_MAX, data=json.dumps({"mensaje": texto, "origen": "voz"}).encode("utf-8"),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(pet, timeout=5) as r:
                r.read()
            return True
        except Exception as exc:
            print(f"  [max no responde] {exc} -> perdido: \"{texto}\"")
            return False

    def _pegar(self, texto):
        if self._cambiar_destino(texto):
            return
        if self._a_max() and not self.simulado:
            self.buffer_max = getattr(self, "buffer_max", []) + [texto]
            self.hay_texto_sin_enviar = True
            self.ultimo_texto = texto
            self.ultimo_pegado = time.time()
            print(f"  > [max] {texto}")
            return
        if self.simulado:
            self.hay_texto_sin_enviar = True
            self.ultimo_texto = texto
            self.ultimo_pegado = time.time()
            print(f"  > [simulado] {texto}")
            return

        def escribir():
            previo = ""
            try:
                previo = pyperclip.paste()
            except Exception:
                pass
            pyperclip.copy((" " if self.hay_texto_sin_enviar else "") + texto)
            with self.teclado.pressed(Key.ctrl):
                self.teclado.press("v")
                self.teclado.release("v")
            time.sleep(0.15)
            try:
                pyperclip.copy(previo)
            except Exception:
                pass

        if self._con_foco_en_destino(escribir):
            self.hay_texto_sin_enviar = True
            self.ultimo_texto = texto
            self.ultimo_pegado = time.time()
            print(f"  > {texto}")
        else:
            print(f"  [perdido] \"{texto}\"")

    def _enviar(self):
        if self.simulado:
            self.hay_texto_sin_enviar = False
            self.texto_dudoso = False
            print("  [enviado - simulado]")
            return

        def pulsar_enter():
            self.teclado.press(Key.enter)
            self.teclado.release(Key.enter)

        self.hay_texto_sin_enviar = False
        self.texto_dudoso = False
        self.espera_usuario = False
        if self._a_max():
            if self._enviar_a_max():
                print("  [enviado a Max]")
            return
        if self._con_foco_en_destino(pulsar_enter):
            print("  [enviado]")
        else:
            print("  [enter perdido]")

    def _turno_acabado(self, turno, silencio):
        """Probabilidad de que el usuario haya terminado (Smart Turn), o None si no hay modelo.
        Se le pasa lo hablado con solo ~0,3 s de silencio final, como en Pipecat."""
        if self.detector_turno is None:
            try:
                import fin_turno
                self.detector_turno = fin_turno.FinDeTurno()
            except Exception as exc:
                print(f"  [fin de turno] desactivado: {exc}")
                self.detector_turno = False
        if not self.detector_turno or not turno:
            return None
        audio = np.concatenate(turno)
        sobra = int(max(0.0, silencio - 0.3) * SAMPLE_RATE)
        if sobra and len(audio) > sobra:
            audio = audio[:-sobra]
        try:
            return self.detector_turno(audio)
        except Exception as exc:
            print(f"  [fin de turno] error: {exc}")
            return None

    # --- teclas de control ---

    def _pitar(self, frecuencia, duracion=120):
        """Aviso sonoro del cambio de estado: sin ventana visible es la unica
        forma de saber si esta escuchando o pausado."""
        try:
            import winsound

            threading.Thread(
                target=winsound.Beep, args=(frecuencia, duracion), daemon=True
            ).start()
        except Exception:
            pass

    def _jarvis_hablando(self):
        """la voz de Claude crea HABLANDO mientras suena: se ignora el micro.

        La marca se refresca cada segundo mientras habla, asi que un margen corto
        basta: si la voz de Claude muere de golpe, el micro vuelve en 4 s y no en 2 min.
        """
        try:
            return time.time() - os.path.getmtime(str(Path(__file__).resolve().parent.parent / "voz" / "HABLANDO")) < 4
        except OSError:
            return False

    def _texto_jarvis(self):
        """Lo que Jarvis está diciendo: servidor_voz.py lo escribe en la marca HABLANDO."""
        try:
            return Path(str(Path(__file__).resolve().parent.parent / "voz" / "HABLANDO")).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return ""

    def _aprender_voz(self):
        """MÓDULO DE APRENDIZAJE DE VOZ (continuo): voz_usuario.aprender en segundo plano,
        al arrancar y cada APRENDER_CADA frases nuevas. Si mejora, se recargan perfiles."""
        if not self.cfg.get("aprender_voz", True) or self.aprendiendo:
            return

        def tarea():
            self.aprendiendo = True
            try:
                import voz_usuario
                voz_usuario.aprender(log=lambda l: print(f"  [aprendizaje de voz] {l}"))
                self.huellas = None  # se recargan con los perfiles nuevos al próximo uso
            except Exception as exc:
                print(f"  [aprendizaje de voz falló] {exc}", file=sys.stderr)
            finally:
                self.aprendiendo = False

        threading.Thread(target=tarea, daemon=True).start()

    def _parecidos(self, audio):
        """(parecido al usuario, parecido al eco) según la huella de voz, o None si no hay
        modelo/perfiles o el trozo es muy corto."""
        if self.huellas is False:
            return None
        try:
            if self.huellas is None:
                import voz_usuario
                self.huellas = voz_usuario.Huellas()
                if not self.huellas.perfiles:
                    self.huellas = False
                    return None
            return self.huellas.parecidos(audio)
        except Exception as exc:
            print(f"  [huella de voz no disponible] {exc}", file=sys.stderr)
            self.huellas = False
            return None

    def _huella(self, audio):
        """Diferencia de parecido el usuario - eco, o None. >0 suena al usuario, <0 a Jarvis."""
        p = self._parecidos(audio)
        return None if p is None else p[0] - p[1]

    def _otra_persona(self, audio):
        """Con Jarvis callado: True si la voz NO es la del usuario (otra persona de la
        habitación, una nota de voz, o un invento de Whisper sobre ruido). 03-oct:
        se colaron "estoy saliendo ahora mismo de casa..." (ajeno) y "¡Gracias!" (ruido)."""
        if not self.cfg.get("filtro_otras_personas", True):
            return False, None
        import voz_usuario
        p = self._parecidos(audio[-8 * SAMPLE_RATE:])
        if p is None:
            return False, None  # muy corto o sin huella: mejor dejarlo pasar
        return p[0] < voz_usuario.OTRA_PERSONA, p[0]

    def _restar_altavoces(self, modelo, texto, audio, fin):
        """Quita lo que estaba sonando por los altavoces (vídeo de fondo) del texto del
        micro. Se transcribe la captura de los altavoces del mismo rato y eco.restar
        tira los tramos que salen en las dos (03-oct). Sin captura, el texto tal cual."""
        if not self.altavoces or not self.altavoces.activo():
            return texto, False
        sonado = self.altavoces.ventana(fin, len(audio) / SAMPLE_RATE + 1.5)
        if not self.altavoces.suena(sonado):
            return texto, False
        try:
            segs, _ = modelo.transcribe(sonado, language=self.cfg["idioma"], vad_filter=True,
                                        beam_size=1)
            oido_altavoz = " ".join(s.text.strip() for s in segs if s.no_speech_prob < 0.6)
        except Exception as exc:
            print(f"  [altavoces] no transcrito: {exc}", file=sys.stderr)
            return texto, False
        # 05-oct 19:30: un "Sí." del usuario se tiraba porque Jarvis/vídeo también dijo "sí".
        # Respuestas de 1-2 palabras no se restan: perder un "sí" bloquea la conversación
        if len(texto.split()) <= 2:
            return texto, False
        resto = eco.restar(texto, oido_altavoz)
        antes, quedan = len(texto.split()), len(resto.split())
        if antes >= 10 and quedan <= antes * 0.5:
            # 04-oct 19:09: de 45 palabras del vídeo quedó "deber." y se pegó. 19:13: de 88
            # quedaron 24 ("sensor filetro... ir al baño"), el mismo vídeo mal casado entre
            # micro y loopback. Si la mitad o más sonaba por los altavoces, el resto también
            print(f"  [altavoz] resto del vídeo tirado: \"{resto[:60]}\" ({antes} -> {quedan} palabras)")
            resto = ""
        if resto != texto:
            print(f"  [altavoz] quitado de \"{texto[:90]}\" -> \"{resto[:90]}\""
                  f" ({len(texto.split())} -> {len(resto.split())} palabras)")
        # 04-oct: si la captura no cubre todo lo grabado (frase larga, hueco en el
        # loopback), lo que queda puede ser vídeo sin restar: no saltarse la huella
        cubierto = len(sonado) / SAMPLE_RATE >= len(audio) / SAMPLE_RATE - 2.0
        if not cubierto:
            print(f"  [altavoces] captura parcial ({len(sonado) / SAMPLE_RATE:.0f} de "
                  f"{len(audio) / SAMPLE_RATE:.0f} s): se mira la huella igual")
        return resto, cubierto

    def _quitar_tramos_ajenos(self, audio, segmentos):
        """Filtro palabra a palabra (03-oct 18:50): el usuario hablando A LA VEZ que un vídeo,
        Whisper junta las dos voces en un trozo ("Hola, ¿me oyes? Pero además
        introduciremos un sistema de...") y la huella del trozo entero sale a medias.
        Se agrupan las palabras en tramos de ~2 s, se mide la huella de cada uno y se
        quitan los que no suenan al usuario. None = no se quitó nada (o no se pudo medir)."""
        # 03-oct 18:52: APAGADO por defecto. En uso real, la voz del usuario MEZCLADA con el
        # vídeo dio 0,13-0,34 (igual que el vídeo solo, 0,01-0,37): la huella no separa
        # voces superpuestas, se tiraba lo del usuario y tardaba 30 s. Encender: "filtro_tramos"
        if not self.cfg.get("filtro_tramos", False):
            return None
        if not self.cfg.get("filtro_otras_personas", True) or len(audio) < 3 * SAMPLE_RATE:
            return None
        import voz_usuario
        # los tramos no cruzan de un segmento de Whisper a otro: el cambio de voz suele
        # caer en un corte de segmento, y un tramo mitad el usuario mitad vídeo sale dudoso
        tramos, tramos_seg = [], []  # (nº de segmento, palabras); tramos por segmento
        for seg in segmentos:
            if seg.no_speech_prob >= 0.6 or seg.avg_logprob <= -1.0 or not seg.words:
                continue
            propios, actual = [], []
            for w in seg.words:
                actual.append(w)
                if actual[-1].end - actual[0].start >= 2.0:
                    propios.append(actual)
                    actual = []
            if actual:
                if propios and actual[-1].end - actual[0].start < 1.0:
                    propios[-1] += actual  # un resto corto no se mide solo: la huella dudaría
                else:
                    propios.append(actual)
            tramos += [(len(tramos_seg), t) for t in propios]
            tramos_seg.append(len(propios))
        if len(tramos) < 2:
            return None  # un solo tramo: ya lo juzga el filtro del trozo entero
        juicio = []  # (segmento, texto, parecido o None, ajeno)
        for n, t in tramos:
            ini = max(0, int((t[0].start - 0.1) * SAMPLE_RATE))
            fin = min(len(audio), int((t[-1].end + 0.1) * SAMPLE_RATE))
            p = self._parecidos(audio[ini:fin])
            ajeno = p is not None and p[0] < voz_usuario.OTRA_PERSONA
            juicio.append((n, "".join(w.word for w in t).strip(), p and p[0], ajeno))
        # si la mitad o más de un segmento suena ajena, fuera el segmento entero: en
        # la prueba un tramo del vídeo dio 0,36 en medio de otros a 0,19-0,22 y se colaba
        ajenos_seg = collections.Counter(n for n, _, _, a in juicio if a)
        quedan, quitados = [], []
        for n, texto_t, p, ajeno in juicio:
            if ajeno or ajenos_seg[n] * 2 >= tramos_seg[n]:
                quitados.append(texto_t if p is None else f"{texto_t} ({p:+.2f})")
            else:
                quedan.append(texto_t)
        if not quitados:
            return None
        for q in quitados:
            print(f"  [tramo ajeno] \"{q[:100]}\"")
        return " ".join(quedan).strip()

    def _filtrar_eco(self, texto, dicho, audio=None, contexto=None):
        """Trozo grabado mientras Jarvis hablaba: eco, orden de corte o el usuario por encima.

        Decide el TEXTO (eco.py) y la VOZ (huella) a la vez: solo se calla a Jarvis si
        el texto no es su eco y la voz no suena claramente a él. Medido el 02-oct con
        ventanas de 1 s: margen 0,05 reconoce al usuario ~73 % y toma el eco por el usuario ~3 %.
        """
        dif = self._huella(audio) if audio is not None else None  # trozo de 1 s
        dif2 = self._huella(contexto) if contexto is not None and len(contexto) > len(audio) else dif
        voz = "" if dif is None else f" voz {dif:+.2f}/{dif2:+.2f}"
        if audio is not None and len(texto.split()) >= 8 and not eco.es_eco(texto, dicho):
            # 03-oct 18:40: frases largas de un vídeo se colaron como "corte"/"encima":
            # con Jarvis hablando también se filtra la voz ajena
            ajena, parecido = self._otra_persona(audio)
            if ajena:
                print(f"  [otra persona] \"{texto[:80]}\" voz {parecido:+.2f}")
                return "", "dudoso"
        if eco.es_corte(texto, dicho):
            # "¡para!" tiene que cortar rápido y con 1 s la huella duda más: solo se
            # ignora la orden si la voz es CLARAMENTE la de Jarvis
            if dif is not None and dif < -HUELLA_VETO_CORTE:
                print(f"  [eco por voz] \"{texto}\"{voz}")
                return "", "eco"
            self._callar_jarvis()
            print(f"  [corte] \"{texto}\"{voz} {time.strftime('%H:%M:%S')}")
            return ("" if eco.solo_corte(texto) else texto), "corte"
        if eco.es_eco(texto, dicho):
            print(f"  [eco] \"{texto}\"{voz}")
            # 07-oct 20:27: "Sí."/"Sigo." del usuario (voz +0,11..+0,23) se tiraron como eco porque
            # Jarvis acababa de decir "sí o no"/"sigo": respuesta corta con su voz = es el usuario
            if len(texto.split()) <= 3 and dif is not None and (dif >= 0.10 or (dif2 is not None and dif2 >= 0.15)):
                self._callar_jarvis()
                print(f"  [respuesta corta del usuario encima de Jarvis]{voz}")
                return texto, "encima"
            # 03-oct: el usuario dictaba "venga", "vamos", "a ver" mientras Jarvis decía lo mismo:
            # el texto lo daba por eco y se guardaba como eco con SU voz, ensuciando el
            # perfil del eco (confusión 1 % -> 6 %). Si la huella dice claramente el usuario, se
            # guarda como 'dudoso' (no entrena nada).
            return "", ("dudoso" if dif2 is not None and dif2 > ECO_QUE_ES_USUARIO else "eco")
        if dif2 is not None and dif2 <= HUELLA_MARGEN:
            # el texto no cuadra con lo que dice Jarvis, pero la voz es la suya: eco mal oído
            print(f"  [eco por voz] \"{texto}\"{voz}")
            return "", "eco"
        # ni eco ni orden, y la voz es del usuario (o no se sabe): Jarvis se calla
        self._callar_jarvis()
        print(f"  [el usuario por encima: Jarvis callado]{voz}")
        return texto, "encima"

    def _guardar_muestra(self, audio, etiqueta, texto):
        """Guarda el trozo con su etiqueta (usuario / eco / corte / encima) en muestras_voz,
        para entrenar y medir el reconocimiento de la voz del usuario. Máx. MUESTRAS_MAX."""
        import wave
        try:
            MUESTRAS.mkdir(exist_ok=True)
            nombre = f"{time.strftime('%Y%m%d_%H%M%S')}_{int(time.time() * 1000) % 1000:03d}_{etiqueta}"
            with wave.open(str(MUESTRAS / f"{nombre}.wav"), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(SAMPLE_RATE)
                w.writeframes((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())
            with open(MUESTRAS / "indice.tsv", "a", encoding="utf-8") as f:
                f.write(f"{nombre}\t{etiqueta}\t{texto}\n")
            if etiqueta == "solo":
                self.nuevas_solo += 1
                if self.nuevas_solo >= APRENDER_CADA:
                    self.nuevas_solo = 0
                    self._aprender_voz()
            # las muestras del usuario (_usuario y grabaciones) no se borran nunca: son su huella
            viejos = sorted(w for w in MUESTRAS.glob("*.wav")
                            if not w.stem.endswith("_usuario") and not w.stem.startswith("grabacion_")
                            )[:-MUESTRAS_MAX]
            for v in viejos:
                v.unlink(missing_ok=True)
        except Exception as exc:
            print(f"  [muestra no guardada] {exc}", file=sys.stderr)

    def _callar_jarvis(self):
        """Pide a la voz de Claude que se calle (el usuario le ha hablado por encima)."""
        import socket

        try:
            with socket.create_connection(("127.0.0.1", 50321), timeout=1) as s:
                s.sendall(b'{"cmd":"parar"}\n')
                s.recv(16)
        except OSError:
            pass

    def _tecla(self, tecla):
        if tecla == Key.f9:
            self.activo = not self.activo
            print("\n== PAUSADO ==" if not self.activo else "\n== ESCUCHANDO ==")
            self._pitar(880 if self.activo else 350)
        elif tecla == Key.f10:
            ahora = time.monotonic()
            # F9/F10 estan pegadas: una sola pulsacion de F10 (a veces sin
            # querer, al buscar F9) no debe cerrar el proceso entero.
            # Hace falta repetirla en menos de 2 s para confirmar la salida.
            if ahora - self.ultimo_f10 < 2.0:
                self.salir = True
                self._pitar(250, 250)
                return False
            self.ultimo_f10 = ahora
            print("\n== F10 pulsa otra vez en <2s para salir ==")
            self._pitar(500, 60)
        elif tecla == Key.f11:
            self.fijar_destino_actual()
            self._pitar(1200, 80)

    # --- bucle principal ---

    def ejecutar(self):
        from faster_whisper import WhisperModel

        # El listener va antes de cargar el modelo: F9/F10 son la salida de emergencia
        # y deben responder tambien durante los ~35 s de carga.
        Listener(on_press=self._tecla).start()

        print(f"Cargando modelo '{self.cfg['modelo']}' en {self.cfg['dispositivo']}...")
        try:
            modelo = WhisperModel(
                self.cfg["modelo"],
                device=self.cfg["dispositivo"],
                compute_type="float16" if self.cfg["dispositivo"] == "cuda" else "int8",
            )
        except Exception as exc:
            print(f"Fallo en GPU ({exc}).\nReintentando en CPU (mas lento)...")
            modelo = WhisperModel(self.cfg["modelo"], device="cpu", compute_type="int8")

        if self.salir:
            print("Cancelado durante la carga.")
            return

        self.altavoces = None
        if self.cfg.get("restar_altavoces", True):  # 03-oct: quitar el vídeo de fondo
            import altavoces
            self.altavoces = altavoces.Altavoces()
            if self.altavoces.arrancar():
                print(f"  [altavoces] restando lo que suena por: {self.altavoces.nombre}")
        threading.Thread(target=self._worker, args=(modelo,), daemon=True).start()
        self._aprender_voz()  # una pasada de aprendizaje de voz al arrancar
        if self.cfg["fin_turno"]:  # carga Smart Turn ya: la 1ª pausa no espera al modelo
            self._turno_acabado([np.zeros(SAMPLE_RATE, dtype="float32")], 0.0)

        stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            blocksize=BLOQUE,
            channels=1,
            dtype="float32",
            device=self.cfg["microfono"],
            callback=self._callback,
        )

        with stream:
            detector = DetectorDeVoz()
            print("\nESCUCHANDO. F9 pausa/reanuda · F10 salir.\n")
            self._pitar(660, 90)
            time.sleep(0.1)
            self._pitar(880, 90)

            preroll = deque(maxlen=PREROLL_BLOQUES)
            frase = []
            hablando = False
            silencio = 0.0
            dur_bloque = BLOQUE / SAMPLE_RATE
            interruptor = Interruptor(self.cfg)
            jarvis_sonando = False
            ignorar_marca_hasta = 0.0
            dicho, dicho_hasta = "", 0.0  # lo último que dijo Jarvis y hasta cuándo vale
            historial = deque()  # (momento, texto) de lo que ha ido diciendo Jarvis

            previo = [None, 0.0]  # último trozo encolado y cuándo (contexto para la huella)
            turno = deque(maxlen=int(8 / dur_bloque))  # últimos 8 s, para Smart Turn
            turno_evaluado = False  # Smart Turn se mira una vez por pausa
            revision_ruido = [0.0]  # última vez que se miró si el "habla" de fondo es el usuario

            def encolar(audio):
                if len(audio) / SAMPLE_RATE < self.cfg["duracion_minima_frase"]:
                    return
                # La huella acierta más con 2 s que con 1 s (medido 02-oct: el usuario 90 % /
                # eco 3 % frente a 83 % / 4 %): se le pasa también el final del trozo
                # anterior si es seguido. El texto y la orden de corte siguen con 1 s.
                contexto = audio
                if previo[0] is not None and time.time() - previo[1] < 1.5:
                    contexto = np.concatenate([previo[0][-int(CONTEXTO_HUELLA * SAMPLE_RATE):], audio])
                previo[0], previo[1] = audio, time.time()
                with self.lock:
                    self.pendientes += 1
                self.trabajos.put((audio, dicho if time.time() < dicho_hasta else None, contexto,
                                   time.time()))

            # ajustes que se pueden tocar en config.json sin reiniciar (03-oct)
            EN_CALIENTE = ("fin_turno", "segundos_turno_acabado", "umbral_turno",
                           "segundos_para_enviar", "filtro_otras_personas", "enviar_automatico",
                           "destino", "restar_altavoces", "empezar_a_hablar", "seguir_hablando",
                           "ganancia_micro")
            config_visto = [CONFIG_PATH.stat().st_mtime if CONFIG_PATH.exists() else 0, time.time()]

            while not self.salir:
                try:
                    bloque = self.audio.get(timeout=0.5)
                except queue.Empty:
                    continue

                # 14-oct: ganancia por software del micro (config "ganancia_micro", 1.0 = sin cambio)
                _g = float(self.cfg.get("ganancia_micro", 1.0) or 1.0)
                if _g != 1.0:
                    bloque = np.clip(bloque * _g, -1.0, 1.0)

                if time.time() - config_visto[1] > 3:
                    config_visto[1] = time.time()
                    try:
                        mtime = CONFIG_PATH.stat().st_mtime
                        if mtime != config_visto[0]:
                            config_visto[0] = mtime
                            nueva = cargar_config()
                            cambios = {k: nueva[k] for k in EN_CALIENTE if nueva.get(k) != self.cfg.get(k)}
                            self.cfg.update(cambios)
                            if cambios:
                                print(f"  [config] {cambios}")
                    except (OSError, ValueError) as exc:
                        print(f"  [config ilegible] {exc}")

                if not self.activo:
                    frase, hablando, silencio = [], False, 0.0
                    detector.reiniciar()
                    continue

                jarvis = time.time() > ignorar_marca_hasta and self._jarvis_hablando()
                if jarvis and not interruptor.cfg["interrumpir_hablando"]:
                    # Filtro de eco por palabras (idea de otro proyecto de voz): mientras
                    # Jarvis habla se sigue transcribiendo y el worker decide si es su
                    # eco, una orden de corte o el usuario. Ya no se tira la frase en curso
                    # (era el fallo "Jarvis pisa el dictado" del 25-sep).
                    # se compara con todo lo dicho en los últimos segundos, no solo con
                    # la frase actual: el eco llega con retraso y Jarvis cambia de frase
                    actual = self._texto_jarvis()
                    if actual and (not historial or historial[-1][1] != actual):
                        historial.append((time.time(), actual))
                    while historial and time.time() - historial[0][0] > MEMORIA_ECO:
                        historial.popleft()
                    dicho = " ".join(t for _, t in historial) or actual or dicho
                    dicho_hasta = time.time() + COLA_ECO
                elif jarvis:
                    # MÓDULO AURICULARES (por volumen). Jarvis habla: el micro no transcribe, pero si el usuario le habla
                    # por encima (más fuerte que el eco) se le calla y se le escucha
                    if not jarvis_sonando:
                        jarvis_sonando = True
                        interruptor.reiniciar()
                    voz = interruptor(bloque, detector(bloque))
                    if voz is None:
                        frase, hablando, silencio = [], False, 0.0
                        continue
                    self._callar_jarvis()
                    n, eco = interruptor.ultimo
                    print(f"  [interrumpido] voz {n:.3f} > eco {eco:.3f}")
                    # la marca tarda en desaparecer: se ignora un momento
                    ignorar_marca_hasta = time.time() + 2.0
                    jarvis_sonando = False
                    detector.reiniciar()  # que el eco no contamine el estado de Silero
                    frase, hablando, silencio = list(voz), True, 0.0
                    continue
                if jarvis_sonando:
                    jarvis_sonando = False
                    detector.reiniciar()  # que el eco no arrastre el estado de Silero

                probabilidad = detector(bloque)
                turno.append(bloque)

                # Envío pese al ruido (03-oct): con música o un vídeo de fondo el detector
                # cree que alguien sigue hablando, el silencio no llega nunca y el texto
                # se quedaba sin enviar ("Suena bien." esperó hasta que el usuario volvió a
                # hablar). Si hay texto pegado hace más de segundos_para_enviar + 1 s y lo
                # que suena ahora NO es la voz del usuario (huella), se envía igual.
                # 14:53: solo si lo pegado sonaba claramente al usuario (se coló y se envió
                # una frase del vídeo que el usuario tenía puesto).
                if (
                    self.cfg["enviar_automatico"]
                    and self.hay_texto_sin_enviar
                    and not self.texto_dudoso
                    and not jarvis
                    and time.time() - self.ultimo_pegado > self.cfg["segundos_para_enviar"] + 1.0
                    and time.time() - revision_ruido[0] > 1.0
                ):
                    revision_ruido[0] = time.time()
                    with self.lock:
                        ocupado = self.pendientes > 0
                    if not ocupado:
                        reciente = np.concatenate(list(turno)[-int(2 / dur_bloque):])
                        ajena, parecido = self._otra_persona(reciente)
                        if ajena:
                            print(f"  [envío pese al ruido] lo que suena no es el usuario ({parecido:+.2f})")
                            self._enviar()
                            turno.clear()
                            frase, hablando, silencio = [], False, 0.0
                            continue

                # Histeresis: cuesta mas empezar a hablar que seguir hablando, asi no
                # se cortan finales de frase ni silabas flojas.
                limite = (
                    self.cfg["seguir_hablando"]
                    if hablando
                    else self.cfg["empezar_a_hablar"]
                )

                if probabilidad > limite:
                    if not hablando:
                        frase.extend(preroll)
                        hablando = True
                    frase.append(bloque)
                    silencio = 0.0
                    turno_evaluado = False
                    if jarvis and len(frase) * dur_bloque >= TROZO_CON_JARVIS:
                        encolar(np.concatenate(frase))
                        frase = []  # sigue 'hablando': el trozo siguiente empieza ya
                    continue

                preroll.append(bloque)
                silencio += dur_bloque

                if hablando:
                    frase.append(bloque)
                    # con Jarvis hablando se corta antes: un "¡para!" tiene que llegar ya
                    corte = SILENCIO_CON_JARVIS if jarvis else self.cfg["segundos_para_transcribir"]
                    if silencio >= corte:
                        audio = np.concatenate(frase)
                        frase, hablando = [], False
                        encolar(audio)
                    continue

                if not (self.cfg["enviar_automatico"] and self.hay_texto_sin_enviar):
                    continue
                if (
                    self.cfg["fin_turno"]
                    and not turno_evaluado
                    and not jarvis
                    and not self.espera_usuario
                    and silencio >= self.cfg["segundos_turno_acabado"]
                    and silencio < self.cfg["segundos_para_enviar"]
                ):
                    with self.lock:
                        ocupado = self.pendientes > 0
                    if not ocupado:  # el texto de la última frase ya está pegado
                        turno_evaluado = True
                        p = self._turno_acabado(turno, silencio)
                        if p is not None:
                            from fin_turno import texto_inacabado
                            inacabado = texto_inacabado(self.ultimo_texto)
                            if p >= self.cfg["umbral_turno"] and not inacabado:
                                print(f"  [fin de turno] {p:.2f} -> envío a {silencio:.1f} s")
                                self._enviar()
                                turno.clear()
                                continue
                            print(f"  [turno abierto] {p:.2f}"
                                  + (" (texto sin acabar)" if inacabado else "") + " -> espera")
                if silencio >= self.cfg["segundos_para_enviar"] and not self.espera_usuario:
                    with self.lock:
                        ocupado = self.pendientes > 0
                    if not ocupado:
                        self._enviar()
                        turno.clear()

        print("\nFin.")


def main():
    cfg = cargar_config()
    if "--listar-micros" in sys.argv:
        print(sd.query_devices())
        return
    simulado = "--prueba" in sys.argv
    if simulado:
        print("MODO PRUEBA: transcribe pero no escribe ni envia.\n")
    # Instancia unica (05-oct): tres activar.ps1 casi simultaneos levantaron tres
    # dictados y cada frase llegaba triplicada. El pid se escribe tarde; el mutex no.
    import ctypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _mutex = k32.CreateMutexW(None, False, "Local\\DictadoVozClaude")
    if not simulado and ctypes.get_last_error() == 183:
        print("YA HAY OTRO DICTADO EN MARCHA: salgo.")
        return
    PID_PATH.write_text(str(os.getpid()), encoding="utf-8")
    try:
        Dictado(cfg, simulado).ejecutar()
    except KeyboardInterrupt:
        print("\nInterrumpido.")
    finally:
        PID_PATH.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
