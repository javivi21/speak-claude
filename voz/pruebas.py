"""Banco de pruebas por niveles de la voz de Claude.

Cada nivel es más duro que el anterior. Se ejecutan en orden y se para en el
primero que falle, para no enmascarar la causa.

    .venv\\Scripts\\python.exe pruebas.py            # hasta el nivel alcanzado + 1
    .venv\\Scripts\\python.exe pruebas.py --nivel 4  # solo ese nivel
    .venv\\Scripts\\python.exe pruebas.py --todos    # todos los niveles

El nivel superado se guarda en nivel.json: la cadena de mejora sube de nivel
cuando un nivel nuevo pasa entero.
"""
import json
import random
import re
import socket
import string
import subprocess
import sys
import threading
import time
from pathlib import Path

import leer_ultima as l

RAIZ = Path(__file__).parent
ESTADO = RAIZ / "nivel.json"
MARCA = RAIZ / "HABLANDO"


class Fallo(AssertionError):
    pass


def exigir(condicion, mensaje):
    if not condicion:
        raise Fallo(mensaje)


def servidor_vivo():
    return l.pedir_al_servidor({"cmd": "ping"}, timeout=3) == "ok"


def asegurar_servidor():
    if servidor_vivo():
        return True
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-File", str(RAIZ / "arrancar.ps1"), "-Silencioso"],
                   capture_output=True, timeout=90)
    return servidor_vivo()


def callar():
    l.pedir_al_servidor({"cmd": "parar"}, timeout=3)


# --- niveles ----------------------------------------------------------------

def nivel_1_basico():
    """Lo mínimo: el servidor responde, habla y calla."""
    exigir(asegurar_servidor(), "el servidor no arranca")
    exigir(l.pedir_al_servidor({"cmd": "hablar", "texto": "Nivel uno."}) == "ok", "no habla")
    exigir(l.pedir_al_servidor({"cmd": "parar"}) == "ok", "no obedece al parar")
    exigir(l.pedir_al_servidor({"cmd": "desconocido"}) == "desconocido", "no rechaza lo raro")


def nivel_2_texto():
    """Textos difíciles: vacíos, enormes, con símbolos y acentos."""
    casos = [
        ("", "vacio"), ("   \n\t ", "vacio"),
        ("Ñandú güisqui, ¿qué tal? ¡Bien! 21 grados, 50 euros.", "ok"),
        ("a" * 5000, "ok"),  # por encima del tope: se recorta, no revienta
        ("palabra " * 3000, "ok"),
        ("\x00\x01 texto con bytes raros \x7f", "ok"),
    ]
    for texto, espera in casos:
        r = l.pedir_al_servidor({"cmd": "hablar", "texto": texto}, timeout=60)
        exigir(r == espera, f"texto {texto[:20]!r}: esperaba {espera}, dio {r!r}")
        callar()
    exigir(servidor_vivo(), "el servidor murió con los textos raros")


def nivel_3_concurrencia():
    """Varias peticiones a la vez sin pisarse ni tumbar el servidor."""
    for cuantas in (6, 15, 30):
        res = []
        hilos = [threading.Thread(target=lambda i=i: res.append(
            l.pedir_al_servidor({"cmd": "hablar", "texto": f"Concurrencia {i}."}, timeout=30)))
            for i in range(cuantas)]
        t0 = time.time()
        [h.start() for h in hilos]
        [h.join() for h in hilos]
        tardo = time.time() - t0
        exigir(all(r in ("ok", "ocupado") for r in res),
               f"{cuantas} a la vez: respuestas raras {set(res)}")
        exigir(tardo < cuantas * 1.5, f"{cuantas} a la vez tardó {tardo:.1f} s")
        callar()
    exigir(servidor_vivo(), "el servidor murió con la concurrencia")


def nivel_4_protocolo():
    """Clientes hostiles: basura, JSON partido, cortes de conexión."""
    def crudo(datos, esperar_respuesta=True, cerrar_antes=False):
        try:
            s = socket.create_connection(("127.0.0.1", l.PUERTO), timeout=5)
            s.sendall(datos)
            if cerrar_antes:
                s.close()
                return None
            s.settimeout(5)
            try:
                return s.recv(256)
            finally:
                s.close()
        except OSError:
            return b""

    crudo(b"esto no es json\n")
    crudo(b'{"cmd":"hablar","texto":"a medias')  # JSON incompleto
    crudo(b'{"cmd":"ping"}', cerrar_antes=True)  # corta sin esperar
    crudo(b"")  # conexión vacía
    crudo(b'{"cmd":"hablar","texto":"' + b"x" * 90000 + b'"}\n')  # petición enorme
    exigir(servidor_vivo(), "el servidor murió con peticiones hostiles")
    exigir(l.pedir_al_servidor({"cmd": "hablar", "texto": "Sigo en pie."}) == "ok",
           "tras el ataque ya no habla")
    callar()


def nivel_5_resiliencia():
    """Se mata el servidor a mitad de frase: nada de micrófono sordo."""
    l.pedir_al_servidor({"cmd": "hablar", "texto":
                         "Frase larga que se va a cortar por la mitad a proposito."})
    time.sleep(1)
    exigir(MARCA.exists(), "no se puso la marca del micrófono")
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-File", str(RAIZ / "parar.ps1")], capture_output=True, timeout=30)
    time.sleep(5)
    if MARCA.exists():
        edad = time.time() - MARCA.stat().st_mtime
        exigir(edad > 4, f"marca huérfana con solo {edad:.1f} s: el dictado seguiría sordo")
    exigir(asegurar_servidor(), "no rearranca tras matarlo")
    exigir(not MARCA.exists(), "el arranque no limpió la marca huérfana")


def nivel_6_integracion():
    """El hook de verdad, de punta a punta, y la lectura textual."""
    transcripts = sorted(
        (Path.home() / ".claude" / "projects").glob("*/*.jsonl"),
        key=lambda p: p.stat().st_mtime)
    exigir(transcripts, "no hay transcript con el que probar")
    ruta = str(transcripts[-1])

    p = subprocess.run([str(l.PY), str(RAIZ / "leer_ultima.py")],
                       input=json.dumps({"transcript_path": ruta}), text=True,
                       capture_output=True, timeout=60)
    exigir(p.returncode == 0, f"el hook falló: {p.stderr[-200:]}")
    time.sleep(0.5)
    callar()

    p = subprocess.run([str(l.PY), str(RAIZ / "leer_ultima.py"), "--textual", ruta, "2"],
                       capture_output=True, text=True, timeout=60)
    exigir(p.returncode == 0, f"la lectura textual falló: {p.stderr[-200:]}")
    time.sleep(0.5)

    # una lectura textual no se deja interrumpir por un resumen
    l.pedir_al_servidor({"cmd": "hablar", "texto": "Lectura textual en curso, larga.",
                         "prioridad": True})
    time.sleep(0.3)
    r = l.pedir_al_servidor({"cmd": "hablar", "texto": "Resumen que intenta colarse."})
    exigir(r == "ocupado", f"el resumen interrumpió la lectura textual: {r!r}")
    callar()

    for entrada in ("no es json", "{}", '{"transcript_path":"C:/no/existe.jsonl"}'):
        p = subprocess.run([str(l.PY), str(RAIZ / "leer_ultima.py")], input=entrada,
                           text=True, capture_output=True, timeout=30)
        exigir(p.returncode == 0, f"el hook reventó con {entrada!r}")


def nivel_7_resumen_fuzz():
    """Mil textos generados al azar: ni excepciones ni resúmenes absurdos."""
    trozos = ["hecho:", "`archivo.py:12`", "Ñandú", "¿qué tal?", "¡vale!", "2,7 segundos",
              "21:12", "```python\nx=1\n```", "- punto de lista", "| tabla |",
              "https://ejemplo.com", "C:\\Users\\usuario\\x.py", "resumen_hablado()",
              "0x00000008", "texto normal y corriente", "VOZ: resumen dictado", "",
              "MAYÚSCULAS", "emoji ok", "...", "—", "«comillas»"]
    rnd = random.Random(7)
    for i in range(1000):
        texto = " ".join(rnd.choice(trozos) for _ in range(rnd.randint(1, 25)))
        try:
            r = l.resumen_hablado(texto)
        except Exception as e:
            raise Fallo(f"excepción con {texto[:60]!r}: {type(e).__name__}: {e}")
        exigir(isinstance(r, str) and r, f"resumen vacío con {texto[:60]!r}")
        exigir(len(r) <= l.MAX_CARACTERES + 40, f"resumen larguísimo ({len(r)})")
        exigir("```" not in r and "http" not in r, f"se coló código o enlace: {r[:60]!r}")
    # regresión (21-sep): rutas con barra sin unidad y corte a mitad de cláusula
    r = l.resumen_hablado("Están en ~\\.claude\\skills\\ y en \\Proyectos\\voz\\ listas para usar ya.")
    exigir("\\" not in r and "claude skills" not in r, f"se coló una ruta: {r!r}")
    largo = "Esta es una frase larga, " + "con muchas cláusulas encadenadas, " * 20 + "y termina por fin"
    r = l.resumen_hablado(largo)
    exigir(not r.rstrip(".").endswith((" por", " con", " y", " de")), f"corte a mitad de frase: {r[-40:]!r}")
    # y lo mismo con texto totalmente aleatorio
    for i in range(200):
        basura = "".join(rnd.choice(string.printable) for _ in range(rnd.randint(0, 400)))
        try:
            l.resumen_hablado(basura)
            l.texto_textual(basura)
        except Exception as e:
            raise Fallo(f"excepción con basura: {type(e).__name__}: {e}")


def nivel_8_estres():
    """Cien frases seguidas: la latencia no se degrada y la memoria no se dispara."""
    exigir(asegurar_servidor(), "sin servidor")
    latencias = []
    for i in range(100):
        t0 = time.time()
        r = l.pedir_al_servidor({"cmd": "hablar", "texto": f"Frase numero {i} del estres."},
                                timeout=30)
        latencias.append(time.time() - t0)
        exigir(r in ("ok", "ocupado"), f"frase {i}: {r!r}")
    callar()
    primeras = sum(latencias[:10]) / 10
    ultimas = sum(latencias[-10:]) / 10
    exigir(ultimas < primeras * 3 + 0.5,
           f"la latencia se degrada: {primeras:.2f} s -> {ultimas:.2f} s")
    exigir(servidor_vivo(), "el servidor murió en el estrés")
    mem = memoria_servidor()
    exigir(mem is None or mem < 900, f"memoria disparada: {mem:.0f} MB")
    return f"latencia {primeras:.2f}->{ultimas:.2f} s, memoria {mem:.0f} MB" if mem else None


def memoria_servidor():
    try:
        p = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "
             "'*servidor_voz*' } | Measure-Object WorkingSetSize -Maximum).Maximum"],
            capture_output=True, text=True, timeout=30)
        return int(p.stdout.strip()) / 1e6
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def nivel_9_ia_local():
    """Max, la IA local, inventa los casos difíciles y la voz tiene que aguantarlos."""
    import max_adversario as max_

    frases = max_.casos(10)
    exigir(asegurar_servidor(), "sin servidor")
    problemas = []
    for frase in frases:
        # 1) el resumen no debe romperse ni dejar jerga sin decir
        try:
            r = l.resumen_hablado(frase)
        except Exception as e:
            raise Fallo(f"el resumen reventó con {frase[:50]!r}: {type(e).__name__}")
        exigir(isinstance(r, str) and r, f"resumen vacío con {frase[:50]!r}")
        for feo in ("```", "http", "VOZ:", "\\", "_"):
            if feo in r:
                problemas.append(f"{feo!r} sin limpiar en: {r[:60]!r}")
        # 2) y la voz tiene que poder decirlo
        resp = l.pedir_al_servidor({"cmd": "hablar", "texto": frase}, timeout=60)
        exigir(resp in ("ok", "vacio"), f"la voz falló con {frase[:50]!r}: {resp!r}")
        callar()
        # 3) también en modo textual, que no resume
        try:
            l.texto_textual(frase)
        except Exception as e:
            raise Fallo(f"el textual reventó con {frase[:50]!r}: {type(e).__name__}")
    exigir(not problemas, "; ".join(problemas[:3]))
    exigir(servidor_vivo(), "el servidor murió con los casos de la IA")
    return f"{len(frases)} casos de {'IA local' if max_.ollama_vivo() else 'reserva'}"


def nivel_10_naturalidad():
    """Max juzga si lo que se dice suena natural, con respuestas reales de verdad."""
    import max_adversario as max_

    exigir(max_.ollama_vivo(), "el nivel 10 necesita Ollama en marcha")
    transcripts = sorted(
        (Path.home() / ".claude" / "projects").glob("*/*.jsonl"),
        key=lambda p: p.stat().st_mtime)
    exigir(transcripts, "no hay transcript con el que probar")
    textos = []
    for ruta in reversed(transcripts):  # sesión nueva sin respuestas largas: tirar de las anteriores
        textos = [t for t in l.textos_asistente(str(ruta)) if len(t) > 200][-8:] + textos
        if len(textos) >= 8:
            break
    textos = textos[-8:]
    exigir(len(textos) >= 4, "hacen falta respuestas reales largas para juzgar")

    notas, flojos = [], []
    for bruto in textos:
        sin_etiqueta = l.ETIQUETA.sub("", bruto)  # se juzga el resumen automático
        dicho = l.resumen_hablado(sin_etiqueta)
        nota, motivo = max_.juzgar(l.limpiar_base(sin_etiqueta, corte=False), dicho)
        if nota is None:
            continue  # el juez no contestó: no se penaliza
        notas.append(nota)
        if nota < 4:
            flojos.append(f"{nota:.0f}/10 ({motivo}): {dicho[:70]!r}")
    exigir(len(notas) >= 3, "el juez no pudo puntuar casi nada")
    media = sum(notas) / len(notas)
    exigir(not flojos, "resúmenes que suenan mal: " + " | ".join(flojos[:2]))
    exigir(media >= 6, f"naturalidad media baja: {media:.1f}/10")
    return f"naturalidad media {media:.1f}/10 en {len(notas)} respuestas reales"


def analizar_audio(texto, velocidad=1.0):
    """Sintetiza a fichero y mide el audio: ritmo, cortes, silencios, saturación."""
    import numpy as np
    import soundfile as sf

    destino = RAIZ / "muestras" / "_prueba.wav"
    p = subprocess.run([str(l.PY), str(RAIZ / "hablar.py"), "--sin-audio",
                        "--velocidad", str(velocidad), "--guardar", str(destino), texto],
                       capture_output=True, text=True, timeout=120)
    exigir(p.returncode == 0, f"no se pudo sintetizar: {p.stderr[-150:]}")
    audio, sr = sf.read(destino, dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    dur = len(audio) / sr
    palabras = max(1, len(re.findall(r"\w+", texto)))
    pico = float(np.max(np.abs(audio))) if len(audio) else 0.0

    # silencio = tramos de 20 ms por debajo del 2 % del pico
    ventana = max(1, int(sr * 0.02))
    tramos = audio[: len(audio) // ventana * ventana].reshape(-1, ventana)
    energia = np.abs(tramos).max(axis=1)
    callado = energia < max(pico * 0.02, 1e-4)
    # silencio interno más largo (sin contar los extremos)
    interno, mayor, actual = callado[1:-1] if len(callado) > 2 else callado, 0, 0
    for c in interno:
        actual = actual + 1 if c else 0
        mayor = max(mayor, actual)
    cola = float(np.abs(audio[-int(sr * 0.05):]).max()) if len(audio) > sr * 0.05 else 0.0
    # Piper normaliza al pico, así que el pico SIEMPRE es 1,0: eso no es saturación.
    # Lo que delata el recorte es la proporción de muestras pegadas al máximo.
    saturadas = float((np.abs(audio) > 0.99).mean()) if len(audio) else 0.0
    return {
        "dur": dur, "s_por_palabra": dur / palabras, "pico": pico, "saturadas": saturadas,
        "rms": float(np.sqrt((audio ** 2).mean())) if len(audio) else 0.0,
        "silencio_interno": mayor * 0.02, "energia_final": cola,
        "silencio_total": float(callado.mean()) if len(callado) else 1.0,
    }


def nivel_11_audio():
    """Se escucha el audio de verdad: ritmo, cortes al final, silencios y saturación."""
    import re as _re

    casos = [
        "Listo, ya funciona la voz y suena bien.",
        "El repaso duro de las 20 y 32 a las 20 y 47, con tres fallos encontrados.",
        "Vuelta diez del bucle de mejora, ahora se analiza el audio de verdad, "
        "midiendo el ritmo y los silencios, para que no suene ni atropellado ni lento.",
        "Sí.",
    ]
    problemas = []
    for texto in casos:
        m = analizar_audio(texto)
        palabras = len(_re.findall(r"\w+", texto))
        if palabras >= 3 and not 0.20 <= m["s_por_palabra"] <= 0.75:
            problemas.append(f"ritmo raro {m['s_por_palabra']:.2f} s/palabra en {texto[:30]!r}")
        if m["saturadas"] > 0.005:
            problemas.append(f"audio recortado ({m['saturadas']:.1%} al máximo) en {texto[:30]!r}")
        if m["rms"] < 0.02:
            problemas.append(f"audio casi mudo (rms {m['rms']:.3f}) en {texto[:30]!r}")
        if m["energia_final"] > 0.25:
            problemas.append(f"frase cortada al final ({m['energia_final']:.2f}) en {texto[:30]!r}")
        if m["silencio_interno"] > 1.5:
            problemas.append(f"silencio interno de {m['silencio_interno']:.1f} s en {texto[:30]!r}")
        if m["silencio_total"] > 0.6:
            problemas.append(f"más silencio que voz ({m['silencio_total']:.0%}) en {texto[:30]!r}")
    # la velocidad tiene que notarse de verdad en la duración
    lento = analizar_audio(casos[2], 0.8)["dur"]
    rapido = analizar_audio(casos[2], 1.3)["dur"]
    if not rapido < lento * 0.85:
        problemas.append(f"la velocidad no cambia la duración: {lento:.1f} s vs {rapido:.1f} s")
    exigir(not problemas, "; ".join(problemas[:3]))
    normal = analizar_audio(casos[2])
    return (f"{normal['s_por_palabra']:.2f} s/palabra, recorte {normal['saturadas']:.2%}, "
            f"rms {normal['rms']:.2f}, velocidad 0.8->{lento:.1f}s 1.3->{rapido:.1f}s")


DICTADO = Path(__file__).resolve().parent.parent / "dictado"


def voz_16k(texto, velocidad=1.0):
    """Sintetiza con la voz de Jarvis y la pasa a 16 kHz, como la oye el micro."""
    import numpy as np
    import soundfile as sf

    destino = RAIZ / "muestras" / "_prueba12.wav"
    p = subprocess.run([str(l.PY), str(RAIZ / "hablar.py"), "--sin-audio", "--velocidad",
                        str(velocidad), "--guardar", str(destino), texto],
                       capture_output=True, text=True, timeout=120)
    exigir(p.returncode == 0, f"no se pudo sintetizar: {p.stderr[-150:]}")
    audio, sr = sf.read(destino, dtype="float32")
    destino.unlink(missing_ok=True)
    n = int(len(audio) * 16000 / sr)
    return np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio).astype("float32")


def silero():
    """El mismo detector de voz que usa el dictado (Silero v6), sin cargar Whisper."""
    import numpy as np
    import onnxruntime

    ses = onnxruntime.InferenceSession(
        str(DICTADO / ".venv/Lib/site-packages/faster_whisper/assets/silero_vad_v6.onnx"),
        providers=["CPUExecutionProvider"])
    est = {"h": np.zeros((1, 1, 128), "float32"), "c": np.zeros((1, 1, 128), "float32"),
           "ctx": np.zeros((1, 64), "float32")}

    def prob(bloque):
        ent = np.concatenate([est["ctx"], bloque.reshape(1, -1)], axis=1)
        out, est["h"], est["c"] = ses.run(None, {"input": ent, "h": est["h"], "c": est["c"]})
        est["ctx"] = bloque.reshape(1, -1)[:, -64:]
        return float(np.ravel(out)[0])
    return prob


def simular_micro(senal):
    """Pasa la señal del micro bloque a bloque por Silero + Interruptor.
    Devuelve el segundo en que se interrumpe, o None."""
    if str(DICTADO) not in sys.path:
        sys.path.insert(0, str(DICTADO))
    from interruptor import Interruptor

    prob, it = silero(), Interruptor({"interrumpir_hablando": True})  # se prueba encendido
    for i in range(len(senal) // 512):
        b = senal[i * 512:(i + 1) * 512]
        if it(b, prob(b)) is not None:
            return (i + 1) * 512 / 16000
    return None


def nivel_12_interrumpir():
    """Módulo auriculares: el usuario habla encima y Jarvis se calla (apagado hasta tener auriculares)."""
    import numpy as np

    # 1) regresión: tras 'parar', la marca no puede volver (el dictado quedaba sordo)
    exigir(asegurar_servidor(), "sin servidor")
    r = l.pedir_al_servidor({"cmd": "hablar", "texto": "Esta es una frase larga que se va "
                             "a cortar a la mitad para ver si el micrófono vuelve enseguida."})
    exigir(r == "ok", f"no habló: {r!r}")
    time.sleep(0.6)
    callar()
    time.sleep(1.8)
    exigir(not MARCA.exists(), "tras callar a Jarvis la marca reaparece: el dictado sigue sordo")

    # 1b) regresión (revisión Opus): 'parar' llegado MIENTRAS se sintetiza no puede
    #     dejar que la frase suene después
    hilo = threading.Thread(target=lambda: l.pedir_al_servidor(
        {"cmd": "hablar", "texto": "Otra frase bastante larga para que la síntesis "
         "tarde un poco y el parar llegue antes de que empiece a sonar."}, timeout=30))
    hilo.start()
    time.sleep(0.05)
    callar()
    hilo.join()
    time.sleep(0.5)
    exigir(not MARCA.exists(), "un 'parar' durante la síntesis no cortó: la frase sonó igual")

    rnd = np.random.default_rng(12)
    jarvis = voz_16k("Vale, he revisado el banco de pruebas y todo pasa. La naturalidad sube "
                     "a siete sobre diez y la latencia sigue por debajo de medio segundo.")
    usuario = voz_16k("Para, para, espera un momento, que quiero cambiar otra cosa.", 1.1)
    ruido = lambda n, a=0.002: (rnd.standard_normal(n) * a).astype("float32")

    # 2) solo eco, a volumen normal y a volumen alto: nunca se calla solo
    otra = voz_16k("Mira, el servidor ya carga el modelo una sola vez, así que cada frase sale en "
                   "menos de medio segundo, incluso con textos largos y llenos de cifras.", 1.2)
    for base, gan in ((jarvis, 0.08), (jarvis, 0.3), (jarvis, 0.5), (otra, 0.08), (otra, 0.5)):
        eco = base * gan + ruido(len(base))
        t = simular_micro(eco)
        exigir(t is None, f"se calló solo con su propio eco (ganancia {gan}) a los {t} s")

    # 2b) regresión en vivo (21-sep): silencio inicial y arranque flojo. Aprendía el
    #     eco del silencio de Piper y se cortaba solo al subir el volumen
    for gan in (0.08, 0.3):
        base = np.concatenate([np.zeros(8000, "float32"), jarvis])
        rampa = np.clip(np.arange(len(base)) / 32000, 0.3, 1.0).astype("float32")
        eco = base * rampa * gan + ruido(len(base))
        t = simular_micro(eco)
        exigir(t is None, f"arranque flojo: se calló solo con su eco (ganancia {gan}) a los {t} s")

    # 3) el usuario habla encima a los 2 s CON AURICULARES (fuga de eco mínima, 0,01-0,08):
    #    se calla en menos de 1 s. Con altavoces (eco 0,2) no se exige: falló en vivo
    for gan, gv, limite in ((0.01, 0.6, 3.0), (0.08, 0.6, 3.0), (0.01, 0.3, 3.0)):
        mezcla = jarvis * gan + ruido(len(jarvis))
        ini = 32000
        trozo = usuario[: len(mezcla) - ini] * gv
        mezcla[ini: ini + len(trozo)] += trozo
        t = simular_micro(mezcla)
        exigir(t is not None, f"no se calló con el usuario hablando encima (eco {gan}, voz {gv})")
        exigir(2.0 < t < limite, f"se calló a destiempo: {t} s (el usuario empieza a los 2 s)")

    # 4) golpe o tos corta sobre el eco: no interrumpe
    mezcla = jarvis * 0.08 + ruido(len(jarvis))
    mezcla[40000:41600] += ruido(1600, 0.4)
    t = simular_micro(mezcla)
    exigir(t is None, f"un golpe corto lo calló a los {t} s")

    # 5) el dictado real compila con el cambio
    p = subprocess.run([str(DICTADO / ".venv/Scripts/python.exe"), "-m", "py_compile",
                        str(DICTADO / "dictado.py"), str(DICTADO / "interruptor.py")],
                       capture_output=True, text=True, timeout=60)
    exigir(p.returncode == 0, f"dictado.py no compila: {p.stderr[-200:]}")
    mezcla = jarvis * 0.2 + ruido(len(jarvis))
    trozo = usuario[: len(mezcla) - 32000] * 0.6
    mezcla[32000: 32000 + len(trozo)] += trozo
    t6 = simular_micro(mezcla)
    return ("módulo auriculares (apagado): eco ignorado; el usuario detectado <1 s; golpe ignorado; "
            f"con altavoces: {'no corta' if t6 is None else f'corta en {t6 - 2:.1f} s'}")


def nivel_13_pronunciacion():
    """Las palabras técnicas se dicen bien: se miran los fonemas reales de Piper."""
    from piper import PiperVoice
    import pronunciacion as pr

    v = PiperVoice.load(str(RAIZ / "modelos" / "es_ES-sharvard-medium.onnx"))
    fon = lambda t: "".join("".join(x) for x in v.phonemize(pr.pronunciable(t)))

    # (texto, lo que NO debe sonar, lo que SÍ debe sonar)
    casos = [("los skills", "ʎ", "skˈil"), ("un hook", "ˈoˈok", "xˈuk"),
             ("GitHub", "ˈit ˈub", "ɡˈit"), ("la API", "ˈapi", "ˈa pˈe"),
             ("con Whisper", "wisp", "ɡˈisp"), ("Claude Code", "aʊ", "klˈod kˈoðe"),
             ("Sonnet", "nn", "sonˈet")]
    # los que el usuario quiere tal cual se leen: el diccionario no puede tocarlos
    for nombre in ("Opus", "Jarvis", "Max"):
        exigir(pr.pronunciable(nombre) == nombre, f"el diccionario cambió {nombre!r}")
    malos = []
    for texto, no, si in casos:
        f = fon(texto)
        if no in f or si.replace("ˈ", "") not in f.replace("ˈ", ""):
            malos.append(f"{texto!r} -> {f}")
    exigir(not malos, "suenan mal: " + " | ".join(malos[:3]))

    # el diccionario respeta lo que no es suyo y las mayúsculas
    exigir(pr.pronunciable("hooked y Skills") == "hooked y Eskils".replace("Eskils", "eskils"),
           f"tocó lo que no debía: {pr.pronunciable('hooked y Skills')!r}")
    exigir(pr.pronunciable("") == "" and pr.pronunciable("sin nada") == "sin nada",
           "cambió texto sin palabras técnicas")

    # la pausa entre frases, exacta: una voz simulada con tres frases de 1 s de "audio"
    # tiene que salir con exactamente dos huecos (ni delante ni detrás) y a cualquier velocidad
    import numpy as np

    class Chunk:
        sample_rate = 16000
        audio_float_array = np.ones(16000, dtype="float32")

    class VozFalsa:
        def synthesize(self, texto, syn_config=None):
            return [Chunk()]  # una frase = un trozo (el código parte el texto en frases)

    for vel in (1.0, 1.3):
        audio, sr = pr.sintetizar_piper(VozFalsa(), "Uno. Dos. Tres.", vel)
        silencio = int((audio == 0).sum())
        esperado = 2 * int(16000 * pr.PAUSA_FRASES / vel)
        exigir(silencio == esperado and audio[0] != 0 and audio[-1] != 0,
               f"pausas mal a velocidad {vel}: {silencio} muestras de silencio, esperaba {esperado}")
    return f"{len(casos)} palabras técnicas bien; pausa entre frases {pr.PAUSA_FRASES} s exacta"


def tono_medio(audio, sr):
    """Tono (Hz) aproximado por autocorrelación en los tramos con voz."""
    import numpy as np

    paso, ventana = int(sr * 0.02), int(sr * 0.04)
    tonos = []
    for i in range(0, len(audio) - ventana, paso):
        f = audio[i:i + ventana] - np.mean(audio[i:i + ventana])
        if np.sqrt(np.mean(f ** 2)) < 0.05:
            continue
        ac = np.correlate(f, f, "full")[ventana - 1:]
        lo, hi = int(sr / 400), int(sr / 70)
        pico = lo + int(np.argmax(ac[lo:hi]))
        if ac[pico] > 0.4 * ac[0]:
            tonos.append(sr / pico)
    return float(np.median(tonos)) if tonos else 0.0


def nivel_15_flujo_y_expresividad():
    """Habla en cuanto está la primera frase, se corta en seco a mitad y da más vida a ¿?¡!."""
    import numpy as np
    import pronunciacion as pr
    import voces
    from piper import PiperVoice

    exigir(asegurar_servidor(), "sin servidor")
    largo = ("Vale, ya está. He revisado el banco de pruebas y todo pasa sin problemas. "
             "La naturalidad sube a siete sobre diez y la latencia sigue muy por debajo. "
             "Dime qué te parece y seguimos con lo siguiente. Si quieres, cambiamos la voz. "
             "También podemos afinar el ritmo y las pausas entre frases.")
    # 1) latencia al primer sonido en un texto largo: la respuesta llega tras la 1ª frase
    tiempos = []
    for _ in range(5):
        t0 = time.time()
        r = l.pedir_al_servidor({"cmd": "hablar", "texto": largo})
        tiempos.append(time.time() - t0)
        exigir(r == "ok", f"no habló: {r!r}")
        callar()
        time.sleep(0.3)
    media = sum(tiempos) / len(tiempos)
    exigir(media < 0.3, f"tarda {media:.2f} s en empezar a hablar (esperaba < 0,3 s)")

    # 2) cortar a mitad de un texto largo: la marca desaparece y NO vuelve después
    l.pedir_al_servidor({"cmd": "hablar", "texto": largo})
    time.sleep(1.0)
    exigir(MARCA.exists(), "no había marca mientras hablaba")
    callar()
    time.sleep(0.2)
    exigir(not MARCA.exists(), "tras callar, la marca sigue")
    time.sleep(4)  # a esas alturas seguirían sonando (y refrescando) las frases siguientes
    exigir(not MARCA.exists(), "tras callar, una frase posterior resucitó la marca")

    # 3) una lectura larga acaba sola y limpia
    l.pedir_al_servidor({"cmd": "hablar", "texto": "Primera frase corta. Segunda frase corta."})
    time.sleep(6)
    exigir(not MARCA.exists(), "la lectura terminó y dejó la marca puesta")

    # 4) expresividad por frase: una exclamación o pregunta se mueve más que una afirmación,
    #    y con expresividad 0 no cambia nada
    v = PiperVoice.load(str(RAIZ / "modelos" / "es_ES-sharvard-medium.onnx"))
    base = voces.estilo("F")

    def st(hz_a, hz_b):  # semitonos entre dos tonos
        return 12 * np.log2(hz_a / hz_b)

    def medir(texto, fuerza, veces=3):
        """(subida del tono al final, tono medio en Hz, duración) promediando varias síntesis."""
        sub, hz, dur = [], [], []
        for _ in range(veces):
            a, sr = pr.sintetizar_piper(v, texto, 1.0, {**base, "expresividad": fuerza})
            n = int(sr * 0.4)
            cola, cabeza = tono_medio(a[-n:], sr), tono_medio(a[:-n], sr)
            if cola > 0 and cabeza > 0:
                sub.append(st(cola, cabeza))
            hz.append(tono_medio(a, sr))
            dur.append(len(a) / sr)
        return float(np.mean(sub)), float(np.mean(hz)), float(np.mean(dur))

    # (a) preguntas: el tono al final sube más con expresividad que sin ella
    preg = "¿De verdad crees que esto va a funcionar tan bien como dices tú?"
    s1, _, _ = medir(preg, 1.0, veces=6)
    s0, _, _ = medir(preg, 0.0, veces=6)
    exigir(s1 - s0 > 0.8, f"la pregunta no sube al final: {s1:.2f} vs {s0:.2f} semitonos")
    # (b) exclamaciones: más agudas y más rápidas
    exc = "¡Qué bien, lo hemos conseguido por fin, esto es genial!"
    _, h1, _ = medir(exc, 1.0)
    _, h0, _ = medir(exc, 0.0)
    exigir(st(h1, h0) > 0.5, f"la exclamación no es más aguda: {st(h1, h0):.2f} semitonos")
    # El ritmo NO se mide en audio: Piper varía la duración ~2 % de una síntesis a otra
    # (tanto como el efecto). Se comprueba la configuración, que es determinista.
    cfg = lambda t, f: pr._configuracion({**base, "expresividad": f}, 1.0, t).length_scale
    exigir(cfg(exc, 1.0) < 1.0 and cfg(preg, 1.0) > 1.0,
           f"ritmo mal: exclamación {cfg(exc, 1.0)}, pregunta {cfg(preg, 1.0)}")
    # (c) afirmaciones: estables, como eligió el usuario (config y audio idénticos con y sin expresividad)
    afi = "Esto es una afirmación normal y corriente, sin nada especial."
    exigir(pr._tipo_frase(afi) == "", "una afirmación se tomó por pregunta o exclamación")
    exigir(cfg(afi, 1.0) == cfg(afi, 0.0), "la expresividad toca el ritmo de las afirmaciones")
    trozos = [(np.ones(4000, "float32"), 22050)]
    exigir(pr._dar_vida(trozos, "", 1.0) is trozos, "la expresividad modifica el audio de una afirmación")
    return (f"1ª frase en {media:.2f} s; corte en seco sin marca; pregunta +{s1 - s0:.1f} st al final; "
            f"exclamación +{st(h1, h0):.1f} st; afirmaciones sin tocar")


def nivel_14_dos_voces():
    """Las dos voces (masculina original y femenina) existen, se cambian y suenan distinto."""
    import voces
    from piper import PiperVoice
    import pronunciacion as pr

    exigir(asegurar_servidor(), "sin servidor")
    original = voces.actual()
    try:
        # 1) protocolo: cambiar, consultar, rechazar lo desconocido, hablar con voz concreta
        exigir(l.pedir_al_servidor({"cmd": "voz", "cual": "femenina"}) == "F", "no cambió a la femenina")
        exigir(l.pedir_al_servidor({"cmd": "voz"}) == "F", "no recuerda la voz activa")
        exigir(voces.actual() == "F", "el cambio no se guardó en voces.json")
        exigir(l.pedir_al_servidor({"cmd": "voz", "cual": "robot"}) == "voz desconocida",
               "aceptó una voz que no existe")
        exigir(l.pedir_al_servidor({"cmd": "hablar", "texto": "Prueba.", "voz": "robot"})
               == "voz desconocida", "habló con una voz que no existe")
        exigir(voces.actual() == "F", "una voz rara cambió la activa")
        r = l.pedir_al_servidor({"cmd": "hablar", "texto": "Prueba de la voz masculina.", "voz": "M"})
        exigir(r == "ok", f"no habló con la voz M pedida: {r!r}")
        callar()
        exigir(l.pedir_al_servidor({"cmd": "voz", "cual": "masculina"}) == "M", "no volvió a la masculina")

        # 2) suenan distinto de verdad: el tono medio de F es claramente más agudo que el de M
        v = PiperVoice.load(str(RAIZ / "modelos" / "es_ES-sharvard-medium.onnx"))
        frase = "Vale, ya está. Ahora hablo con esta voz, y dime qué te parece."
        a_m, sr = pr.sintetizar_piper(v, frase, 1.0, voces.estilo("M"))
        a_f, _ = pr.sintetizar_piper(v, frase, 1.0, voces.estilo("F"))
        tm, tf = tono_medio(a_m, sr), tono_medio(a_f, sr)
        exigir(tm > 0 and tf > 0, f"no se pudo medir el tono ({tm:.0f}/{tf:.0f} Hz)")
        exigir(tf > tm * 1.25, f"las voces suenan casi igual: M {tm:.0f} Hz, F {tf:.0f} Hz")

        # 2b) la voz L (logo) lleva efectos: suena distinto de F con el mismo texto,
        #     y sin saturar ni estropear la duración
        import numpy as np
        a_l, _ = pr.sintetizar_piper(v, frase, 1.0, voces.estilo("L"))
        exigir(np.isfinite(a_l).all() and np.max(np.abs(a_l)) <= 1.0, "la voz L saturó o dio valores raros")
        exigir(abs(len(a_l) - len(a_f)) < 0.5 * sr, "los efectos de L cambiaron la duración de más")
        exigir(np.mean(np.abs(a_l[:len(a_f)] - a_f[:len(a_l)])) > 0.005, "L suena igual que F: no aplicó efectos")
        exigir(l.pedir_al_servidor({"cmd": "voz", "cual": "logo"}) == "L", "no cambió a la voz logo")
        exigir(l.pedir_al_servidor({"cmd": "hablar", "texto": "Prueba de la voz logo."}) == "ok",
               "no habló con la voz logo")
        callar()

        # 3) un voces.json roto o ausente no tumba nada: vuelve a lo de fábrica
        copia = voces.ARCHIVO.read_text(encoding="utf-8") if voces.ARCHIVO.exists() else None
        try:
            voces.ARCHIVO.write_text("{esto no es json", encoding="utf-8")
            exigir(voces.actual() == "M" and voces.estilo(), "voces.json roto no se recuperó")
        finally:
            if copia is not None:
                voces.ARCHIVO.write_text(copia, encoding="utf-8")
            else:
                voces.ARCHIVO.unlink(missing_ok=True)
    finally:
        voces.fijar(original)  # la prueba no deja cambiada la voz elegida por el usuario
        callar()
    return f"M {tm:.0f} Hz, F {tf:.0f} Hz y L con efectos; cambio por protocolo; archivo roto tolerado"


def nivel_16_naturalidad_medida():
    """Sin altavoz. Lo que se midió mal el 24-sep y se corrigió: volumen igual en todas
    las frases, arranques suaves, pausas regulares, preguntas sí/no que suben y
    parciales (¿qué...?) que caen, fechas y siglas bien dichas. Probado en M y F."""
    import numpy as np
    import pronunciacion as pr
    import voces
    from piper import PiperVoice

    for t, bien in [("12 GB", "12 gigas"), ("el 24-09-2026", "el 24 de septiembre de 2026"),
                    ("la URL", "la u erre ele"), ("ok", "oquei"), ("MMA", "MMA")]:
        exigir(pr.pronunciable(t) == bien, f"{t!r} -> {pr.pronunciable(t)!r}")
    exigir(pr.pregunta_parcial("Vale, ¿y cómo lo hacemos?") and not pr.pregunta_parcial("¿Seguimos?"),
           "no distingue preguntas parciales de las de sí/no")

    v = PiperVoice.load(str(RAIZ / "modelos" / "es_ES-sharvard-medium.onnx"))
    texto = "Vale, ya está hecho. ¿Lo pruebo ahora? Hay que mirar el servidor. ¡Genial!"
    for cual in ("M", "F"):
        trozos = list(pr.frases_piper(v, texto, 1.0, voces.estilo(cual)))
        rms, arranques, huecos = [], [], []
        for a, sr in trozos:
            voz = np.flatnonzero(np.abs(a) > 0.02)
            rms.append(float(np.sqrt(np.mean(a[np.abs(a) > 0.02] ** 2))))
            arranques.append(float(np.max(np.abs(a[voz[0]:voz[0] + int(sr * 0.01)]))) / float(np.max(np.abs(a))))
            huecos.append(voz[0] / sr)
        salto = 20 * np.log10(max(rms) / min(rms))
        exigir(salto < 2.5, f"{cual}: el volumen salta {salto:.1f} dB entre frases")
        # antes: 0,81 del pico en los 10 primeros ms (golpe); una vocal inicial suave, < 0,6
        exigir(max(arranques) < 0.6, f"{cual}: arranque brusco ({max(arranques):.2f} del pico en 10 ms)")
        exigir(all(0.25 < h < 0.6 for h in huecos[1:]), f"{cual}: pausas irregulares {huecos[1:]}")
        exigir(max(float(np.max(np.abs(a))) for a, _ in trozos) < 0.99, f"{cual}: satura")

    def subida(t, cual):
        s = []
        for _ in range(3):
            a, sr = pr.sintetizar_piper(v, t, 1.0, voces.estilo(cual))
            n = int(sr * 0.4)
            c, h = tono_medio(a[-n:], sr), tono_medio(a[:-n], sr)
            if c and h:
                s.append(12 * np.log2(c / h))
        return float(np.mean(s))

    for cual in ("F",):  # M: sin retoques de tono por decisión del usuario (24-sep)
        sn = subida("¿De verdad crees que esto va a funcionar?", cual)
        pa = subida("¿Qué te parece lo que hemos hecho hoy?", cual)
        exigir(sn - pa > 2.5, f"{cual}: sí/no {sn:+.1f} st no sube frente a parcial {pa:+.1f}")
    return f"volumen parejo, arranques suaves, pausas regulares; sí/no {sn:+.1f} st, parcial {pa:+.1f} st"


NIVELES = [nivel_1_basico, nivel_2_texto, nivel_3_concurrencia, nivel_4_protocolo,
           nivel_5_resiliencia, nivel_6_integracion, nivel_7_resumen_fuzz, nivel_8_estres,
           nivel_9_ia_local, nivel_10_naturalidad, nivel_11_audio, nivel_12_interrumpir,
           nivel_13_pronunciacion, nivel_14_dos_voces, nivel_15_flujo_y_expresividad,
           nivel_16_naturalidad_medida]


# --- ejecución --------------------------------------------------------------

def leer_nivel():
    try:
        return json.loads(ESTADO.read_text(encoding="utf-8")).get("superado", 0)
    except (OSError, ValueError):
        return 0


def guardar_nivel(n):
    ESTADO.write_text(json.dumps({"superado": n, "fecha": time.strftime("%Y-%m-%d %H:%M")},
                                 ensure_ascii=False, indent=2), encoding="utf-8")


def correr(indices):
    superado = leer_nivel()
    for i in indices:
        f = NIVELES[i - 1]
        t0 = time.time()
        try:
            detalle = f()
            print(f"NIVEL {i} OK   ({time.time() - t0:.1f} s) {f.__doc__.splitlines()[0]}"
                  + (f"\n        {detalle}" if detalle else ""))
            if i == superado + 1:
                superado = i
                guardar_nivel(superado)
        except Fallo as e:
            print(f"NIVEL {i} FALLA ({time.time() - t0:.1f} s): {e}")
            return superado, i
        except Exception as e:
            print(f"NIVEL {i} ERROR ({time.time() - t0:.1f} s): {type(e).__name__}: {e}")
            return superado, i
    return superado, None


if __name__ == "__main__":
    if "--nivel" in sys.argv:
        n = int(sys.argv[sys.argv.index("--nivel") + 1])
        indices = [n]
    elif "--todos" in sys.argv:
        indices = range(1, len(NIVELES) + 1)
    else:
        indices = range(1, min(leer_nivel() + 2, len(NIVELES) + 1))
    sup, fallo = correr(indices)
    # el histórico de nivel.json no dice si ESTA pasada falló (03-oct: decía "16 de 16"
    # con el nivel 10 caído y los 11-16 sin ejecutar)
    if fallo:
        print(f"\nESTA PASADA: falla el nivel {fallo}; los siguientes no se han ejecutado")
    print(f"Nivel superado (histórico): {sup} de {len(NIVELES)}")
    sys.exit(1 if fallo else 0)
