"""Servidor de voz residente: mantiene Piper cargado para hablar al instante.

Sin él, cada frase paga ~2,5 s de carga de modelo. Escucha en 127.0.0.1 y recibe
una línea JSON por petición:
    {"cmd": "hablar", "texto": "...", "prioridad": false}
    {"cmd": "parar"}   {"cmd": "ping"}
    {"cmd": "espera", "tras": 6}   empieza un turno: frase de relleno en 6 s si nadie
                                   habla antes ("tras": 0 = turno acabado, cancela)
    {"cmd": "narrar", "texto": ...} lo que Claude va escribiendo entre paso y paso; espera
                                   a que acabe lo que suena (no lo pisa) y no se repite
Una petición normal corta la lectura en curso; una con prioridad (lectura textual)
no se deja interrumpir por las normales.

Arranque manual:  .venv\\Scripts\\pythonw.exe servidor_voz.py
Lo arranca solo leer_ultima.py cuando hace falta.
"""
import collections
import hashlib
import json
import random
import re
import socket
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import eleven  # noqa: E402
import espera  # noqa: E402
import voces  # noqa: E402
import numpy as np  # noqa: E402
from pronunciacion import frases_piper  # noqa: E402

RAIZ = Path(__file__).parent
PUERTO = 50321
MODELO = RAIZ / "modelos" / "es_ES-sharvard-medium.onnx"
MARCA = RAIZ / "HABLANDO"  # el dictado la mira para no oírse a sí mismo
INACTIVIDAD = 3600  # se apaga tras una hora sin peticiones
LIMITE_TEXTO = 20000  # lectura textual de respuestas largas
# Frases de espera ya sintetizadas con la voz activa (03-oct): antes cada una pedía el
# audio a ElevenLabs en el momento (~0,5 s + arrancar Python en el hook) y llegaba
# tarde y a destiempo. Ahora suenan al instante y solo se pagan una vez.
CACHE = RAIZ / "cache_espera"
RELLENOS_MAX = 0  # coletillas FUERA (03-oct 18:40, el usuario: "no para de meter coletillas, elimina")
RELLENO_CADA = 35.0  # s entre rellenos si el silencio sigue
RELLENO_TRAS_NARRAR = 30.0  # s de silencio tras narrar un paso antes de rellenar


def _reintentar(accion):
    """El dictado LEE la marca (filtro de eco): en Windows, borrarla o escribirla justo
    mientras otro proceso la tiene abierta da PermissionError. Se reintenta un poco y,
    si no hay manera, se sigue: una marca mal puesta nunca puede tumbar una petición."""
    for _ in range(5):
        try:
            accion()
            return
        except FileNotFoundError:
            return
        except OSError:
            time.sleep(0.01)


def quitar_marca():
    _reintentar(lambda: MARCA.unlink(missing_ok=True))


def poner_marca(texto):
    _reintentar(lambda: MARCA.write_text(texto, encoding="utf-8"))


class Salida:
    """UNA salida de audio con búfer y 'callback'. Callar = vaciar el búfer.

    Antes cada lectura abría su propia salida y 'parar' la abortaba mientras otro hilo
    escribía en ella: PortAudio no lo soporta y el servidor moría con "access violation"
    (servidor_crash.log, 21-sep). Aquí solo el callback de PortAudio toca el audio y
    Python solo mete o vacía trozos bajo un candado: no hay nada que abortar.
    """

    REABRIR_TRAS = 5.0  # s de silencio tras los que se reabre, por si el usuario cambió de altavoces

    def __init__(self, sd, sr):
        self.sd, self.sr = sd, sr
        self.lock = threading.Lock()
        self.trozos = collections.deque()
        self.actual, self.pos, self.pendiente = None, 0, 0
        self.stream = None
        self.ultimo_sonido = 0.0

    def _cb(self, outdata, frames, tiempo, estado):
        try:
            n = 0
            with self.lock:
                while n < frames:
                    if self.actual is None:
                        if not self.trozos:
                            break
                        self.actual, self.pos = self.trozos.popleft(), 0
                    tomar = min(frames - n, len(self.actual) - self.pos)
                    outdata[n:n + tomar, 0] = self.actual[self.pos:self.pos + tomar]
                    n += tomar
                    self.pos += tomar
                    if self.pos >= len(self.actual):
                        self.actual = None
                self.pendiente -= n
                if n:
                    self.ultimo_sonido = time.time()
            outdata[n:] = 0
        except Exception:
            outdata.fill(0)  # un fallo aquí nunca puede tumbar el hilo de audio

    def preparar(self):
        """Deja la salida abierta y lista. Si lleva un rato callada se reabre (así coge
        el altavoz o los auriculares que estén activos ahora). Lanza si no hay audio."""
        inactiva = self.pendiente <= 0 and time.time() - self.ultimo_sonido > self.REABRIR_TRAS
        if self.stream is not None and not inactiva and self.stream.active:
            return
        self.cerrar()
        self.stream = self.sd.OutputStream(samplerate=self.sr, channels=1, dtype="float32",
                                           callback=self._cb, latency="low")
        self.stream.start()

    def cerrar(self):
        s, self.stream = self.stream, None
        if s is not None:
            try:
                s.stop()
                s.close()
            except Exception:
                pass

    def encolar(self, audio):
        a = np.ascontiguousarray(audio, dtype="float32")
        with self.lock:
            self.trozos.append(a)
            self.pendiente += len(a)

    def vaciar(self):
        with self.lock:
            self.trozos.clear()
            self.actual, self.pos, self.pendiente = None, 0, 0

    def vacia(self):
        with self.lock:
            return self.pendiente <= 0


class Voz:
    def __init__(self):
        import sounddevice as sd
        from piper import PiperVoice

        self.sd = sd
        self.voz = PiperVoice.load(str(MODELO))
        self.salida = Salida(sd, self.voz.config.sample_rate)
        self.lock = threading.Lock()
        self.prioritario = False
        self.cancelaciones = 0  # 'parar' recibido: anula lo que aún se está sintetizando
        self.generacion = 0  # cada reproducción tiene la suya: evita que un hilo
        self.ultimo_uso = time.time()  # viejo borre la marca de una lectura nueva
        # Piper/onnxruntime NO aguanta varias síntesis a la vez sobre la misma voz:
        # con 30 peticiones simultáneas moría con "access violation". Una cada vez.
        self.sintesis = threading.Lock()
        self.cache = {}  # (voz, texto) -> audio de las frases de espera
        self.temporizador = None  # frase de espera programada (cmd 'espera')
        self.ultima_espera = ""
        # turno en curso (de 'espera' con tras>0 a 'espera' con tras 0): relleno sin
        # repetir frase, como mucho RELLENOS_MAX, y narración de lo que se va haciendo
        self.turno_activo = False
        self.tipo_turno = "orden"  # 'orden' -> "ok, voy"; 'pregunta' -> "a ver, lo miro"
        self.rellenos_dichos = 0
        self.rellenos_usados = set()
        self.narrado = set()
        self.narracion_id = 0
        # 03-oct 15:01: cada respuesta nueva cortaba a media frase la lectura de la anterior
        # ("te cortas a ti mismo"). Ahora espera a que acabe; si llegan varias, vale la última.
        self.cola_id = 0
        self.es_relleno = False  # lo que suena es una coletilla: esa sí se puede cortar
        threading.Thread(target=self._preparar_esperas, daemon=True).start()

    # --- frases de espera -------------------------------------------------------

    def _clave_voz(self):
        cfg = eleven.config()
        return f"eleven-{cfg.get('voz')}" if eleven.activo() else f"piper-{voces.actual()}"

    def _sintetizar_entera(self, texto):
        """Audio completo de una frase corta, con el motor activo (para la caché)."""
        if eleven.activo():
            try:
                trozos = [t[0] for t in eleven.frases(texto, self.voz.config.sample_rate)]
                if trozos:
                    return np.concatenate(trozos)
            except Exception:
                pass
            return None  # sin red: mejor no cachear Piper bajo la clave de Daniel
        with self.sintesis:
            trozos = [t[0] for t in frases_piper(self.voz, texto, 1.0, voces.estilo(None))]
        return np.concatenate(trozos) if trozos else None

    def _de_cache(self, texto):
        """Audio de la caché para esta frase y la voz actual, o None (lo crea si puede)."""
        if texto not in espera.TODAS:
            return None
        clave = (self._clave_voz(), texto)
        if clave in self.cache:
            return self.cache[clave]
        archivo = CACHE / f"{clave[0]}_{hashlib.sha1(texto.encode()).hexdigest()[:10]}.npy"
        try:
            audio = np.load(archivo)
        except (OSError, ValueError):
            audio = self._sintetizar_entera(texto)
            if audio is None:
                return None
            try:
                CACHE.mkdir(exist_ok=True)
                np.save(archivo, audio.astype("float32"))
            except OSError:
                pass
        self.cache[clave] = audio
        return audio

    def _preparar_esperas(self):
        for texto in espera.TODAS:  # en segundo plano al arrancar: la 1ª ya sale al instante
            try:
                self._de_cache(texto)
            except Exception:
                pass

    def empezar_turno(self, tras, tipo="orden"):
        with self.lock:
            self.tipo_turno = tipo
            self.turno_activo = tras > 0
            self.rellenos_dichos = 0
            self.rellenos_usados = set()
            self.narrado = set()
        self.programar_espera(tras)

    def narrar(self, texto):
        """Dice un paso intermedio. Si algo suena, espera a que acabe (máx. 8 s); si
        mientras tanto llega otro paso más nuevo, este se descarta (vale el último)."""
        texto = (texto or "").strip()
        with self.lock:
            if not self.turno_activo or not texto or texto in self.narrado:
                return "ignorado"
            self.narrado.add(texto)
            self.narracion_id += 1
            mia = self.narracion_id

        def tarea():
            fin = time.time() + 8
            while time.time() < fin and (not self.salida.vacia() or MARCA.exists()):
                time.sleep(0.05)
            if mia != self.narracion_id or not self.turno_activo:
                return
            self.hablar(texto)
            if self.turno_activo:  # si sigue el silencio después, un relleno más tarde
                self.programar_espera(RELLENO_TRAS_NARRAR)

        threading.Thread(target=tarea, daemon=True).start()
        return "ok"

    def programar_espera(self, tras):
        with self.lock:
            if self.temporizador is not None:
                self.temporizador.cancel()
                self.temporizador = None
            if tras > 0:
                self.temporizador = threading.Timer(tras, self._decir_espera)
                self.temporizador.daemon = True
                self.temporizador.start()

    def _decir_espera(self):
        with self.lock:
            self.temporizador = None
            if not self.turno_activo or self.rellenos_dichos >= RELLENOS_MAX:
                return
        if (RAIZ / "SILENCIO").exists() or not self.salida.vacia() or MARCA.exists():
            self.programar_espera(3)  # ya está sonando algo: no se pisa, se mira luego
            return
        # nunca la misma frase dos veces en un turno, ni la última del turno anterior
        # el primero de cada turno es un "te he oído" corto; los demás, para silencios largos
        if self.rellenos_dichos == 0:
            pool = espera.FRASES_PREGUNTA if self.tipo_turno == "pregunta" else espera.FRASES_ORDEN
        else:
            pool = espera.FRASES
        opciones = [f for f in pool
                    if f not in self.rellenos_usados and f != self.ultima_espera] or pool
        self.ultima_espera = random.choice(opciones)
        self.rellenos_usados.add(self.ultima_espera)
        self.rellenos_dichos += 1
        self.hablar(self.ultima_espera, es_espera=True)
        if self.rellenos_dichos < RELLENOS_MAX:
            self.programar_espera(RELLENO_CADA)

    def _uno_a_uno(self, frases):
        """Envuelve el generador de frases para que cada trozo se sintetice a solas."""
        while True:
            with self.sintesis:
                try:
                    trozo = next(frases)
                except StopIteration:
                    return
            yield trozo

    def parar(self):
        self.salida.vaciar()  # calla al instante (el callback pasa a sacar silencio)
        quitar_marca()
        self.prioritario = False

    def hablar(self, texto, prioridad=False, velocidad=1.0, cual=None, es_espera=False):
        self.ultimo_uso = time.time()
        if not es_espera:
            self.programar_espera(0)  # llega la respuesta: la frase de espera sobra
        if cual is not None and not voces.nombre_valido(cual):
            return "voz desconocida"
        # los caracteres de control rompen Piper por dentro: fuera antes de nada
        texto = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", texto or "")
        texto = re.sub(r"\s+", " ", texto).strip()[:LIMITE_TEXTO]
        # sin letras ni cifras no hay nada que pronunciar, y Piper revienta con
        # un texto de solo signos ("!!!!!!"): se descarta antes de sintetizar
        if not re.search(r"[^\W_]", texto, re.UNICODE):
            return "vacio"
        if self.prioritario and not prioridad:
            return "ocupado"
        antes = self.cancelaciones
        primero = None
        self.motor = "piper"
        guardado = self._de_cache(texto) if cual is None and velocidad == 1.0 else None
        if guardado is not None:
            frases, primero, self.motor = iter(()), (guardado,), "cache"
        elif eleven.activo():  # Daniel (ElevenLabs); si falla antes de sonar, Piper
            frases = eleven.frases(texto, self.voz.config.sample_rate)
            try:
                primero = next(frases, None)
                self.motor = "eleven" if primero is not None else "piper"
            except Exception as e:
                primero, self.motor = None, f"piper (eleven falló: {type(e).__name__})"
        if primero is None:
            # el estilo se lee del disco en cada petición: cambiar de voz no exige reiniciar
            frases = self._uno_a_uno(frases_piper(self.voz, texto, velocidad, voces.estilo(cual)))
            try:  # solo se espera a la PRIMERA frase: el resto se sintetiza mientras suena
                primero = next(frases, None)
            except Exception as e:  # texto imposible de sintetizar: no tumbar el servidor
                return f"error: {type(e).__name__}"
        if primero is None:
            return "error: sin audio"
        with self.lock:
            # se vuelve a mirar dentro del lock: sintetizar tarda y pudo entrar otra
            if self.prioritario and not prioridad:
                return "ocupado"
            if self.cancelaciones != antes:
                return "ok"  # llegó un 'parar' mientras se sintetizaba: no suena
            self.parar()
            self.prioritario = prioridad
            self.es_relleno = es_espera
            self.generacion += 1
            mia = self.generacion
            try:
                poner_marca(texto)  # el dictado compara lo oído con esto (filtro de eco)
                self.salida.preparar()
                self.salida.encolar(primero[0])
            except Exception as e:  # tarjeta de sonido ocupada, etc.
                quitar_marca()
                self.prioritario = False  # si no, todos los resúmenes darían 'ocupado'
                return f"error: {e}"
        threading.Thread(target=self._alimentar, args=(frases, mia), daemon=True).start()
        return "ok"

    def repetida(self, pet, ventana=30.0):
        """La misma respuesta normal dos veces en 30 s no se dice dos veces (03-oct)."""
        if pet.get("prioridad", False):
            return False
        clave = re.sub(r"\s+", " ", pet.get("texto") or "").strip()
        with self.lock:
            ahora = time.time()
            if clave and clave == getattr(self, "ultimo_texto", "") and ahora - self.ultimo_cuando < ventana:
                return True
            self.ultimo_texto, self.ultimo_cuando = clave, ahora
        return False

    def sonando(self):
        return not self.salida.vacia() or MARCA.exists()

    def hablar_despues(self, texto, velocidad=1.0, cual=None):
        """Respuesta nueva con otra aún sonando: espera a que acabe (máx. 30 s) y la
        dice. Contesta al momento ('encolado') para que el hook no se quede esperando."""
        with self.lock:
            self.cola_id += 1
            mia = self.cola_id

        def tarea():
            fin = time.time() + 30
            while time.time() < fin and self.sonando() and not self.es_relleno:
                if mia != self.cola_id:
                    return
                time.sleep(0.05)
            if mia == self.cola_id:
                self.hablar(texto, False, velocidad, cual)

        threading.Thread(target=tarea, daemon=True).start()
        return "encolado"

    def _alimentar(self, frases, mia):
        """Sintetiza el resto de frases y las va metiendo en la salida mientras suena."""
        vivo = threading.Event()  # mientras dure la lectura, la marca se refresca

        def refrescar():
            # la marca se refresca cada medio segundo: si el servidor muere de golpe,
            # queda vieja y el dictado la ignora enseguida en vez de quedarse sordo.
            # Solo mientras esta lectura siga siendo la vigente Y la marca exista: touch()
            # la crea si falta, y tras un 'parar' resucitaría la marca (dictado sordo)
            while not vivo.is_set() and mia == self.generacion:
                try:
                    if MARCA.exists():
                        MARCA.touch()
                except OSError:
                    pass
                vivo.wait(0.5)

        threading.Thread(target=refrescar, daemon=True).start()
        try:
            while mia == self.generacion:  # si ya habla otra cosa, no se sintetiza más
                trozo = next(frases, None)
                if trozo is None:
                    break
                with self.lock:
                    if mia != self.generacion:
                        break
                    self.salida.encolar(trozo[0])
            while mia == self.generacion and not self.salida.vacia():
                time.sleep(0.02)  # a que suene lo que queda
            fin = time.time() + 0.6  # cola de eco para el micrófono
            while mia == self.generacion and time.time() < fin:
                time.sleep(0.02)
        except Exception:
            pass  # un fallo a mitad: se habla lo que haya y se termina limpio
        finally:
            vivo.set()
            with self.lock:
                if mia == self.generacion:  # si ya habla otra cosa, no tocar su marca
                    quitar_marca()
                    self.prioritario = False


def atender(conn, voz):
    with conn:
        try:
            # una petición larga llega en varios trozos: se lee hasta el salto de
            # línea final, si no el JSON queda partido y no se responde nada
            conn.settimeout(10)
            datos = b""
            pet = None
            while True:
                trozo = conn.recv(65536)
                if not trozo:
                    break  # el cliente cerró: nada más que leer
                datos += trozo
                try:  # se intenta en cada trozo: así vale con salto de línea y sin él
                    pet = json.loads(datos.decode("utf-8", "replace").strip())
                    break
                except ValueError:
                    continue  # JSON aún incompleto: falta otro trozo
        except (OSError, ValueError):
            return
        if pet is None:
            return
        cmd = pet.get("cmd")
        if cmd == "ping":
            resp = "ok"
        elif cmd == "motor":  # qué motor sonó en la última lectura
            resp = getattr(voz, "motor", "ninguno")
        elif cmd == "espera":
            voz.empezar_turno(float(pet.get("tras", 0)), pet.get("tipo", "orden"))
            resp = "ok"
        elif cmd == "narrar":
            resp = voz.narrar(pet.get("texto", ""))
        elif cmd == "parar":
            voz.programar_espera(0)
            with voz.lock:
                # nueva generación: si no, el hilo de la lectura cortada vuelve a
                # crear la marca con touch() y el dictado sigue sordo hasta el final
                voz.generacion += 1
                voz.cancelaciones += 1
                voz.cola_id += 1  # lo que esperaba turno tampoco suena
                voz.parar()
            resp = "ok"
        elif cmd == "voz":  # {"cmd":"voz","cual":"F"} cambia; sin "cual" dice cuál es
            cual = pet.get("cual")
            resp = voces.actual() if cual in (None, "?") else (voces.fijar(cual) or "voz desconocida")
        elif cmd == "hablar" and voz.repetida(pet):
            resp = "repetido"
        elif cmd == "hablar":
            if not pet.get("prioridad", False) and voz.sonando() and not voz.es_relleno:
                resp = voz.hablar_despues(pet.get("texto", ""), float(pet.get("velocidad", 1.0)),
                                          pet.get("voz"))
            else:
                with voz.lock:
                    voz.cola_id += 1  # una respuesta más nueva deja sin turno a la que esperaba
                resp = voz.hablar(pet.get("texto", ""), pet.get("prioridad", False),
                                  float(pet.get("velocidad", 1.0)), pet.get("voz"))
        else:
            resp = "desconocido"
        try:
            conn.sendall(resp.encode())
        except OSError:
            pass


def main():
    # si el proceso muere por un fallo nativo (audio, onnx) que ningún try captura,
    # aquí queda la traza: sin esto la caída no deja rastro (pythonw no tiene consola)
    import faulthandler
    faulthandler.enable(open(RAIZ / "servidor_crash.log", "a"), all_threads=True)
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # sin SO_REUSEADDR: en Windows deja que un segundo proceso robe el puerto y
    # acabas con dos servidores cargando el modelo (300 MB cada uno)
    try:
        srv.bind(("127.0.0.1", PUERTO))
    except OSError:
        return  # ya hay uno escuchando
    srv.listen(8)
    srv.settimeout(60)
    quitar_marca()  # marca huérfana de un cierre anterior
    voz = Voz()
    while True:
        try:
            conn, _ = srv.accept()
        except socket.timeout:
            if time.time() - voz.ultimo_uso > INACTIVIDAD:
                return
            continue
        except OSError:
            return
        threading.Thread(target=atender, args=(conn, voz), daemon=True).start()


if __name__ == "__main__":
    sys.exit(main())
