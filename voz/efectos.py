"""Efectos de audio para dar carácter propio a la voz (solo numpy, sin descargas).

Una 'receta' es un dict, por ejemplo:
    {"tono": 3, "pixel": {"pasos": 3, "bits": 6, "mezcla": 0.5},
     "metal": {"ms": 6, "mezcla": 0.2}, "reverb": {"seg": 0.25, "mezcla": 0.12}}
Se aplica en este orden: tono -> pixel -> metal -> reverb. Audio mono float32.
"""
import numpy as np


def _vocoder(x, rate, n_fft=1024, hop=256):
    """Cambia la duración por 1/rate sin cambiar el tono (vocoder de fase)."""
    win = np.hanning(n_fft).astype("float32")
    x = np.pad(x, (n_fft, n_fft)).astype("float32")
    marcos = 1 + (len(x) - n_fft) // hop
    est = np.stack([np.fft.rfft(win * x[i * hop:i * hop + n_fft]) for i in range(marcos)])
    pasos = np.arange(0, marcos - 1, rate)
    avance = 2 * np.pi * hop * np.arange(est.shape[1]) / n_fft
    fase = np.angle(est[0])
    salida = np.zeros(len(pasos) * hop + n_fft, dtype="float32")
    peso = np.zeros_like(salida)
    for k, t in enumerate(pasos):
        i = int(t)
        f = t - i
        a, b = est[i], est[i + 1]
        mag = (1 - f) * np.abs(a) + f * np.abs(b)
        salida[k * hop:k * hop + n_fft] += win * np.fft.irfft(mag * np.exp(1j * fase), n_fft)
        peso[k * hop:k * hop + n_fft] += win ** 2
        dif = np.angle(b) - np.angle(a) - avance
        fase = fase + avance + dif - 2 * np.pi * np.round(dif / (2 * np.pi))
    salida = salida / np.maximum(peso, 1e-3)
    return salida[n_fft:-n_fft]


def cambiar_tono(x, sr, semitonos):
    """Sube o baja el tono manteniendo la duración (fiable hasta unos ±4 semitonos)."""
    if not semitonos:
        return x
    factor = 2 ** (semitonos / 12)
    estirado = _vocoder(x, 1.0 / factor)  # dura 'factor' veces más; remuestrear lo devuelve
    y = np.interp(np.linspace(0, len(estirado) - 1, len(x)), np.arange(len(estirado)),
                  estirado).astype("float32")
    return y * (np.max(np.abs(x)) / (np.max(np.abs(y)) + 1e-9))


def melodia(x, sr, st_de_t, db_de_t=None, fundido=0.012):
    """Da una curva de entonación y de energía a un trozo de voz.

    `st_de_t(t)` = semitonos en el instante t (s); `db_de_t(t)` = decibelios. Se lee la
    señal a velocidad variable 2**(st/12): el tono sube donde la curva sube, sin artefactos
    de fase (el vocoder no vale para cambiar el tono cada pocos milisegundos). El precio:
    la duración cambia ~5 % y el timbre se desplaza un poco, aceptable con +-2 st.
    Un fundido de entrada evita el "clic" de arranque de las frases.
    """
    n = len(x)
    if n < 64:
        return x
    u = np.arange(int(n * 1.3)) / sr  # rejilla de tiempo de salida (sobra: se recorta)
    tasa = 2.0 ** (np.asarray(st_de_t(u), dtype="float64") / 12.0)
    pos = np.cumsum(tasa)  # posición en la señal de entrada para cada muestra de salida
    m = int(np.searchsorted(pos, n - 1))
    if m < 64:
        return x
    y = np.interp(pos[:m], np.arange(n), x).astype("float32")
    if db_de_t is not None:
        y *= (10.0 ** (np.asarray(db_de_t(u[:m]), dtype="float64") / 20.0)).astype("float32")
    k = min(int(sr * fundido), m)
    if k:
        y[:k] *= (0.5 - 0.5 * np.cos(np.linspace(0, np.pi, k))).astype("float32")
    pico = float(np.max(np.abs(y)))
    if pico > 0.99:  # el acento de energía puede pasar de 1,0: no debe saturar
        y *= 0.99 / pico
    return y


def subida_final(x, sr, semitonos=2.0, seg=0.35):
    """Sube el tono en el último tramo (entonación de pregunta), con fundido suave."""
    n = min(len(x), int(sr * seg))
    if n < 2048 or not semitonos:
        return x
    cola = cambiar_tono(x[-n:], sr, semitonos)
    rampa = np.clip(np.linspace(-0.3, 1.0, n) / 0.7, 0, 1).astype("float32")  # entra al 30 %
    y = x.copy()
    y[-n:] = (1 - rampa) * x[-n:] + rampa * cola
    return y


def pixel(x, sr, pasos=3, bits=6, mezcla=0.5):
    """Voz 'de píxeles' (8 bits): mantiene cada muestra 'pasos' veces y recorta a 'bits'."""
    y = np.repeat(x[::pasos], pasos)[:len(x)]
    niveles = 2 ** (bits - 1)
    y = np.round(y * niveles) / niveles
    return ((1 - mezcla) * x + mezcla * y).astype("float32")


def metal(x, sr, ms=7.0, mezcla=0.3):
    """Una copia retrasada pocos milisegundos: da un timbre metálico de sintetizador."""
    d = max(1, int(sr * ms / 1000))
    y = x.copy()
    y[d:] += mezcla * x[:-d]
    return y


def reverb(x, sr, seg=0.3, mezcla=0.15):
    """Reverberación corta sintética (ruido con caída exponencial)."""
    rnd = np.random.default_rng(7)
    n = int(sr * seg)
    ir = rnd.standard_normal(n) * np.exp(-6.9 * np.arange(n) / n)
    ir /= np.sqrt(np.sum(ir ** 2))
    tam = 1 << int(np.ceil(np.log2(len(x) + n)))
    mojado = np.fft.irfft(np.fft.rfft(x, tam) * np.fft.rfft(ir, tam), tam)[:len(x) + n]
    seco = np.pad(x, (0, n))
    return ((1 - mezcla) * seco + mezcla * mojado * (np.std(x) / (np.std(mojado) + 1e-9))).astype("float32")


def aplicar(x, sr, receta):
    """Aplica una receta y deja el pico en 0,95 para no saturar."""
    if not receta:
        return x
    y = x.astype("float32")
    if receta.get("tono"):
        y = cambiar_tono(y, sr, receta["tono"])
    if receta.get("pixel"):
        y = pixel(y, sr, **receta["pixel"])
    if receta.get("metal"):
        y = metal(y, sr, **receta["metal"])
    if receta.get("reverb"):
        y = reverb(y, sr, **receta["reverb"])
    return (y * (0.95 / (np.max(np.abs(y)) + 1e-9))).astype("float32")
