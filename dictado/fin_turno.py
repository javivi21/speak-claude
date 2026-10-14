"""¿Ha terminado el usuario de hablar? Smart Turn v3.2 (Pipecat, BSD-2, 8,7 MB, CPU).

Mira el AUDIO (entonación, ritmo, cómo cae la frase), no el texto: con él el dictado
no tiene que esperar siempre segundos_para_enviar; si la frase suena acabada, envía
tras una pausa corta. Modelo: modelos/smart-turn-v3.2-cpu.onnx
(huggingface.co/pipecat-ai/smart-turn-v3). Español ~90 % de acierto según Pipecat.

Entrada del modelo: los últimos 8 s a 16 kHz (rellenos con ceros DELANTE), pasados por
el extractor de Whisper (80 mel, 800 tramas). Se reimplementa aquí en numpy, igual que
WhisperFeatureExtractor(chunk_length=8, do_normalize=True) de transformers, para no
instalar transformers ni torch.

  .venv\\Scripts\\python.exe fin_turno.py archivo.wav   # probabilidad de turno acabado
"""
import re
import sys
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).parent
MODELO = RAIZ / "modelos" / "smart-turn-v3.2-cpu.onnx"
SR = 16000
SEGUNDOS = 8
N_FFT, SALTO, N_MEL = 400, 160, 80


def _filtros_mel():
    """Banco mel 'slaney' de Whisper (80 bandas, 0-8000 Hz)."""
    frec = np.fft.rfftfreq(N_FFT, 1.0 / SR)
    mels = np.linspace(0.0, 45.245640471924965, N_MEL + 2)
    f = 200.0 / 3 * mels
    log = mels >= 15.0  # 1000 Hz en la escala slaney
    f[log] = 1000.0 * np.exp(np.log(6.4) / 27.0 * (mels[log] - 15.0))
    dif = np.diff(f)
    rampas = f.reshape(-1, 1) - frec.reshape(1, -1)
    bajo = -rampas[:-2] / dif[:-1, None]
    alto = rampas[2:] / dif[1:, None]
    pesos = np.maximum(0, np.minimum(bajo, alto))
    pesos *= (2.0 / (f[2:N_MEL + 2] - f[:N_MEL]))[:, None]
    return pesos.astype("float32")


_MEL = _filtros_mel()
_VENTANA = (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(N_FFT) / N_FFT)).astype("float32")


def caracteristicas(audio):
    """(1, 80, 800) como WhisperFeatureExtractor(chunk_length=8, do_normalize=True)."""
    n = SEGUNDOS * SR
    x = np.asarray(audio, dtype="float32")[-n:]
    x = np.pad(x, (n - len(x), 0))
    x = (x - x.mean()) / np.sqrt(x.var() + 1e-7)
    x = np.pad(x, N_FFT // 2, mode="reflect")
    tramas = np.lib.stride_tricks.sliding_window_view(x, N_FFT)[::SALTO]
    espectro = np.abs(np.fft.rfft(tramas * _VENTANA, axis=1)) ** 2
    mel = np.log10(np.maximum(_MEL @ espectro.T, 1e-10))[:, :-1]
    mel = np.maximum(mel, mel.max() - 8.0)
    return ((mel + 4.0) / 4.0)[None].astype("float32")


class FinDeTurno:
    def __init__(self):
        import onnxruntime

        opts = onnxruntime.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 2
        opts.log_severity_level = 4
        self.sesion = onnxruntime.InferenceSession(str(MODELO), sess_options=opts,
                                                   providers=["CPUExecutionProvider"])

    def __call__(self, audio):
        """Probabilidad 0..1 de que el turno haya terminado."""
        salida = self.sesion.run(None, {"input_features": caracteristicas(audio)})[0]
        v = float(np.ravel(salida)[0])
        # el ONNX de Pipecat ya devuelve la sigmoide aunque la salida se llame 'logits'
        return v if 0.0 <= v <= 1.0 else float(1 / (1 + np.exp(-v)))


# Palabras con las que una frase en castellano NO acaba (idea de makeAssembler de
# otro proyecto de voz, allí solo en inglés): si el texto termina así, se espera aunque
# el audio suene acabado. Solo palabras gramaticales que nunca cierran una frase
# (fuera 'es', 'está', 'hay', 'más'...: '¿qué hora es?' sí está acabada).
SIGUE = re.compile(
    r"\b(y|e|o|u|ni|pero|sino|que|porque|pues|aunque|si|cuando|como|donde|mientras|"
    r"de|del|a|al|en|con|por|para|sin|sobre|entre|hasta|desde|hacia|según|tras|"
    r"el|la|los|las|un|una|unos|unas|lo|mi|mis|tu|tus|su|sus|nuestro|nuestra|"
    r"este|esta|ese|esa|aquel|aquella|muy|tan|o sea|es decir|"
    r"vamos a|voy a|tienes que|hay que)$",
    re.IGNORECASE)


def texto_inacabado(texto):
    t = texto.strip().lower()
    if not t:
        return True
    if re.search(r"[,;:\-–—]$", t):
        return True
    return bool(SIGUE.search(re.sub(r"[.!?¡¿…\"']+$", "", t).strip()))


if __name__ == "__main__":
    import soundfile as sf

    f = FinDeTurno()
    for ruta in sys.argv[1:]:
        audio, sr = sf.read(ruta, dtype="float32")
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        if sr != SR:
            print(f"{ruta}: necesita 16 kHz (tiene {sr})")
            continue
        print(f"{f(audio):.2f}  {ruta}")
