"""Graba al usuario hablando N segundos y guarda los trozos con voz como muestras "usuario".

Para crear su huella de voz rápido (voz_usuario.py). Jarvis tiene que estar callado.
Uso: .venv\\Scripts\\python.exe grabar_usuario.py [segundos]   (por defecto 60)
"""
import sys
import time
import wave

import numpy as np
import sounddevice as sd

from voz_usuario import MUESTRAS, SR

VENTANA = 1.0  # s por trozo (como los trozos que corta el dictado con Jarvis hablando)


def main():
    segundos = float(sys.argv[1]) if len(sys.argv) > 1 else 60
    print(f"GRABANDO {segundos:.0f} s: habla con normalidad...", flush=True)
    audio = sd.rec(int(segundos * SR), samplerate=SR, channels=1, dtype="float32")
    sd.wait()
    audio = audio[:, 0]
    n = int(VENTANA * SR)
    trozos = [audio[i:i + n] for i in range(0, len(audio) - n + 1, n)]
    niveles = np.array([np.sqrt(np.mean(t ** 2)) for t in trozos])
    # voz = bastante por encima del ruido de fondo de esta misma grabación
    # 02-oct: un umbral por percentil falla si el usuario habla sin pausas (el p20 ya es voz).
    # Igual que voz_usuario.ventanas: fuera lo que esté por debajo de media mediana.
    umbral = 0.5 * float(np.median(niveles))
    MUESTRAS.mkdir(exist_ok=True)
    # la grabación entera también, por si hay que volver a trocearla
    with wave.open(str(MUESTRAS / f"grabacion_{time.strftime('%Y%m%d_%H%M%S')}.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())
    guardados = 0
    with open(MUESTRAS / "indice.tsv", "a", encoding="utf-8") as idx:
        for i, (t, nivel) in enumerate(zip(trozos, niveles)):
            if nivel < umbral:
                continue
            nombre = f"{time.strftime('%Y%m%d_%H%M%S')}_{i:03d}_usuario"
            with wave.open(str(MUESTRAS / f"{nombre}.wav"), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(SR)
                w.writeframes((np.clip(t, -1, 1) * 32767).astype("<i2").tobytes())
            idx.write(f"{nombre}\tusuario\t(grabar_usuario)\n")
            guardados += 1
    print(f"guardados {guardados} trozos con voz de {len(trozos)} (umbral {umbral:.3f})")


if __name__ == "__main__":
    main()
