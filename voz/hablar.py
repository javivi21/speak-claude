"""voz: lee un texto en voz alta con Piper (local, sin internet).

Uso:
  .venv\\Scripts\\python.exe hablar.py --voz sharvard "Hola"
Opciones: --guardar ruta.wav  --sin-audio  --velocidad 1.0
"""
import argparse
from pathlib import Path

import sounddevice as sd
import soundfile as sf

RAIZ = Path(__file__).parent
MODELOS = RAIZ / "modelos"
PIPER_VOCES = {
    "sharvard": "es_ES-sharvard-medium.onnx",
}


def sintetizar_piper(texto, voz, velocidad):
    from piper import PiperVoice
    import voces
    from pronunciacion import sintetizar_piper as sintetizar_con_pausas

    v = PiperVoice.load(str(MODELOS / PIPER_VOCES[voz]))
    # misma voz activa (masculina/femenina) que el servidor: el respaldo no debe cambiarla
    return sintetizar_con_pausas(v, texto, velocidad, voces.estilo())


def hablar(texto, motor="piper", voz="sharvard", velocidad=1.0, guardar=None, reproducir=True):
    audio, sr = sintetizar_piper(texto, voz, velocidad)
    if guardar:
        sf.write(guardar, audio, sr)
    if reproducir:
        import threading
        import time

        marca = Path(__file__).parent / "HABLANDO"
        marca.write_text("1")
        sonando = threading.Event()

        def refrescar():  # el dictado ignora una marca de más de 4 s: hay que
            while not sonando.wait(1):  # refrescarla o se abre el micro a mitad
                try:
                    marca.touch()
                except OSError:
                    pass

        threading.Thread(target=refrescar, daemon=True).start()
        try:
            sd.play(audio, sr)
            sd.wait()
            time.sleep(0.6)  # cola de eco
        finally:
            sonando.set()
            marca.unlink(missing_ok=True)
    return audio, sr


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("texto")
    p.add_argument("--motor", choices=["piper"], default="piper")
    p.add_argument("--voz", default="sharvard")
    p.add_argument("--velocidad", type=float, default=1.0)
    p.add_argument("--guardar")
    p.add_argument("--sin-audio", action="store_true")
    a = p.parse_args()
    hablar(a.texto, a.motor, a.voz, a.velocidad, a.guardar, not a.sin_audio)
