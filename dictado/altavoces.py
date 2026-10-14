"""Graba lo que suena por los altavoces del PC (captura 'loopback' de WASAPI).

Para qué (03-oct): con un vídeo de fondo, el micro coge al usuario Y al vídeo a la vez, y
la huella de voz no sabe separarlos. Aquí se guarda lo que el PC está reproduciendo;
el dictado lo transcribe y quita esas palabras de lo que oyó el micro (eco.restar),
igual que ya se hace con la voz de Jarvis.

Guarda los últimos SEGUNDOS en memoria, a 16 kHz mono, con la hora de cada trozo.
Si no hay altavoz o falla, no pasa nada: activo() da False y el dictado sigue igual.
"""
import collections
import threading
import time

import numpy as np

SR = 16000
SEGUNDOS = 180  # 04-oct: era 40 y una frase de ~60 s de vídeo solo se restaba al final
SUENA_RMS = 0.003  # por debajo, los altavoces están en silencio: no hace falta restar


class Altavoces:
    def __init__(self):
        self.lock = threading.Lock()
        self.trozos = collections.deque()  # (hora de fin, audio 16 kHz)
        self.ok = False
        self.nombre = ""
        self._pa = self._stream = None

    def arrancar(self):
        try:
            import pyaudiowpatch as pa

            self._pa = pa.PyAudio()
            disp = self._pa.get_default_wasapi_loopback()
            self.sr_origen = int(disp["defaultSampleRate"])
            self.canales = max(1, int(disp["maxInputChannels"]))
            self.nombre = disp["name"]
            self._stream = self._pa.open(
                format=pa.paFloat32, channels=self.canales, rate=self.sr_origen,
                input=True, input_device_index=disp["index"],
                frames_per_buffer=int(self.sr_origen * 0.1), stream_callback=self._cb)
            self._stream.start_stream()
            self.ok = True
        except Exception as exc:
            print(f"  [altavoces] sin captura: {exc}")
            self.ok = False
        return self.ok

    def _cb(self, datos, frames, info, estado):
        import pyaudiowpatch as pa

        try:
            a = np.frombuffer(datos, dtype=np.float32).reshape(-1, self.canales).mean(axis=1)
            n = max(1, int(len(a) * SR / self.sr_origen))
            a16 = np.interp(np.linspace(0, len(a) - 1, n), np.arange(len(a)), a).astype("float32")
            ahora = time.time()
            with self.lock:
                self.trozos.append((ahora, a16))
                while self.trozos and ahora - self.trozos[0][0] > SEGUNDOS:
                    self.trozos.popleft()
        except Exception:
            pass
        return (None, pa.paContinue)

    def activo(self):
        return self.ok

    def ventana(self, fin, duracion):
        """Audio de los altavoces entre fin-duracion y fin (hora time.time())."""
        with self.lock:
            sel = [a for t, a in self.trozos if fin - duracion <= t <= fin + 0.2]
        return np.concatenate(sel) if sel else np.zeros(0, dtype="float32")

    @staticmethod
    def suena(audio):
        return len(audio) > SR // 2 and float(np.sqrt((audio ** 2).mean())) > SUENA_RMS

    def cerrar(self):
        try:
            if self._stream is not None:
                self._stream.stop_stream()
                self._stream.close()
            if self._pa is not None:
                self._pa.terminate()
        except Exception:
            pass
