"""Huella de voz: ¿este trozo de audio es el usuario o es el eco de Jarvis por los altavoces?

El filtro por texto (eco.py) falla con trozos cortos o mal oídos. Aquí se compara el
SONIDO: un modelo de reconocimiento de hablante (WeSpeaker ResNet34 entrenado en
VoxCeleb, CC BY 4.0, vía sherpa-onnx) convierte cada trozo en un vector, y se mira si
se parece más a la huella del usuario o a la del eco.

Las huellas se aprenden solas de dictado\\muestras_voz (lo que guarda el dictado):
  - "usuario": frases dictadas con Jarvis callado (casi seguro el usuario)
  - "eco":  trozos que el filtro de texto marcó como eco de Jarvis

Uso:
  .venv\\Scripts\\python.exe voz_usuario.py entrenar   # crea perfiles_voz.npz
  .venv\\Scripts\\python.exe voz_usuario.py medir      # aciertos sin hacer trampa
  .venv\\Scripts\\python.exe voz_usuario.py probar archivo.wav
"""
import sys
import time
import wave
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).parent
# 03-oct: TitaNet large (NVIDIA NeMo, vía sherpa-onnx) en vez de wespeaker resnet34.
# Medido con las muestras del usuario (ventanas 2 s, dejando fuera archivo): el usuario frente a
# eco EER 2,6 % (antes 3,8 %); frente a OTRAS personas el parecido de los ajenos baja
# de 0,50 a 0,06 de mediana (máx 0,18), con el usuario en 0,76. Vuelta atrás: el resnet34
# sigue en modelos/ (cambiar esta línea y "entrenar").
MODELO = RAIZ / "modelos" / "nemo_en_titanet_large.onnx"
MUESTRAS = RAIZ / "muestras_voz"
PERFILES = RAIZ / "perfiles_voz.npz"
SR = 16000
MIN_SEGUNDOS = 0.5  # menos audio que esto no da una huella fiable


def leer_wav(ruta):
    with wave.open(str(ruta), "rb") as w:
        datos = w.readframes(w.getnframes())
    return np.frombuffer(datos, dtype="<i2").astype("float32") / 32768


def etiquetas():
    """{nombre: etiqueta} según indice.tsv (solo los wav que aún existen)."""
    res = {}
    try:
        for linea in (MUESTRAS / "indice.tsv").read_text(encoding="utf-8").splitlines():
            partes = linea.split("\t")
            if len(partes) >= 2 and (MUESTRAS / f"{partes[0]}.wav").exists():
                res[partes[0]] = partes[1]
    except OSError:
        pass
    return res


class Huellas:
    def __init__(self):
        import sherpa_onnx

        cfg = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(MODELO), num_threads=2, provider="cpu")
        self.ext = sherpa_onnx.SpeakerEmbeddingExtractor(cfg)
        self.perfiles = None
        if PERFILES.exists():
            d = np.load(PERFILES)
            self.perfiles = {k: d[k] for k in d.files}

    def huella(self, audio):
        """Vector unitario del hablante, o None si el trozo es demasiado corto."""
        if len(audio) < MIN_SEGUNDOS * SR:
            return None
        s = self.ext.create_stream()
        s.accept_waveform(SR, np.ascontiguousarray(audio, dtype="float32"))
        s.input_finished()
        if not self.ext.is_ready(s):
            return None
        v = np.array(self.ext.compute(s), dtype="float32")
        return v / (np.linalg.norm(v) + 1e-9)

    def parecidos(self, audio):
        """(parecido al usuario, parecido al eco), de -1 a 1; None si no se puede decidir."""
        if not self.perfiles:
            return None
        v = self.huella(audio)
        if v is None:
            return None
        return float(v @ self.perfiles["usuario"]), float(v @ self.perfiles["eco"])

    def es_usuario(self, audio, margen=0.0):
        """True/False si hay huellas y audio suficiente; None si no se sabe."""
        p = self.parecidos(audio)
        if p is None:
            return None
        return p[0] - p[1] > margen


def _perfil(vectores):
    m = np.mean(vectores, axis=0)
    return m / (np.linalg.norm(m) + 1e-9)


VENTANA = 2.0  # s: la huella del dictado usa ~2 s (CONTEXTO_HUELLA); medir, entrenar y
# aprender usan la misma ventana para que las cifras sean comparables (03-oct)


def ventanas(audio):
    """Trocea en ventanas de VENTANA s y se queda con las que tienen voz."""
    n = int(VENTANA * SR)
    trozos = [audio[i:i + n] for i in range(0, len(audio) - n + 1, n)] or [audio]
    niveles = [float(np.sqrt(np.mean(t ** 2))) for t in trozos]
    corte = 0.5 * float(np.median(niveles))  # fuera los silencios entre frases
    return [t for t, nv in zip(trozos, niveles) if nv >= corte]


def cargar_vectores(h):
    """{etiqueta: [(archivo, [huellas de sus ventanas])]} para usuario y eco."""
    vecs = {"usuario": [], "eco": []}
    for nombre, et in sorted(etiquetas().items()):
        if et in vecs:
            try:  # el dictado borra las muestras más viejas (MUESTRAS_MAX) mientras se lee
                audio = leer_wav(MUESTRAS / f"{nombre}.wav")
            except FileNotFoundError:
                continue
            hs = [v for v in (h.huella(t) for t in ventanas(audio)) if v is not None]
            if hs:
                vecs[et].append((nombre, hs))
    return vecs


def entrenar():
    h = Huellas()
    vecs = cargar_vectores(h)
    nj = sum(len(x) for _, x in vecs["usuario"])
    ne = sum(len(x) for _, x in vecs["eco"])
    print(f"ventanas útiles: usuario {nj}, eco {ne}")
    if nj < 5 or ne < 5:
        print("faltan muestras (mínimo 5 ventanas de cada)")
        return False
    np.savez(PERFILES, usuario=_perfil([v for _, x in vecs["usuario"] for v in x]),
             eco=_perfil([v for _, x in vecs["eco"] for v in x]))
    print(f"perfiles guardados en {PERFILES.name}")
    return True


def medir():
    """Validación dejando fuera un ARCHIVO entero: sus ventanas se juzgan con perfiles
    hechos sin él (así no se hace trampa con trozos casi iguales del mismo audio)."""
    h = Huellas()
    vecs = cargar_vectores(h)
    if len(vecs["usuario"]) < 2 or len(vecs["eco"]) < 2:
        print("faltan muestras (mínimo 2 archivos de cada)")
        return
    difs = {"usuario": [], "eco": []}
    for et in ("usuario", "eco"):
        for i, (nombre, hs) in enumerate(vecs[et]):
            resto = {k: [v for j, (_, x) in enumerate(vecs[k]) for v in x if not (k == et and j == i)]
                     for k in ("usuario", "eco")}
            pj, pe = _perfil(resto["usuario"]), _perfil(resto["eco"])
            difs[et] += [float(v @ pj - v @ pe) for v in hs]
    dj, de = np.array(difs["usuario"]), np.array(difs["eco"])
    print(f"ventanas de {VENTANA:g} s: usuario {len(dj)}, eco {len(de)}")
    print(f"  usuario bien (dif > 0): {(dj > 0).mean():.0%}   media {dj.mean():+.3f}  peor {dj.min():+.3f}")
    print(f"  eco  bien (dif < 0): {(de < 0).mean():.0%}   media {de.mean():+.3f}  peor {de.max():+.3f}")
    for m in (0.0, 0.05, 0.1, 0.15, 0.2):
        print(f"  margen {m:.2f}: el usuario reconocido {(dj > m).mean():.0%}, eco tomado por el usuario {(de > m).mean():.0%}")


# --- aprendizaje continuo -------------------------------------------------------------
# Cada sesión de dictado aprende sola: las frases dictadas con Jarvis callado ("solo")
# que suenan claramente al usuario pasan a su huella; las que suenan a otra persona se
# apartan ("otros"). Umbrales medidos el 02-oct con trozos de 2 s: el usuario da parecido
# medio ~0,71 (p10 0,63); la conversación ajena de la habitación, 0,37-0,53.
# Umbrales recalibrados para TitaNet el 03-oct (el usuario p10 0,61 / mediana 0,76; ajenos <= 0,18)
APRENDE_PARECIDO = 0.60  # parecido medio mínimo a la huella del usuario para darla por suya
APRENDE_DIF = 0.15  # y bastante más parecida al usuario que al eco
OTROS_PARECIDO = 0.30  # por debajo: otra persona
# El dictado descarta una frase dicha con Jarvis callado si se parece al usuario menos que
# esto (otra persona o un invento de Whisper sobre ruido, como "¡Gracias!"): ajenos
# medidos <= 0,18, el usuario rechazado ~0,8 % de las ventanas.
OTRA_PERSONA = 0.35  # 03-oct 14:53: subido de 0,25; un vídeo de fondo dio 0,06-0,23 y una
# frase suya se coló. el usuario en sus muestras: mínimo 0,41, mediana 0,79
REGISTRO = RAIZ / "aprendizaje.log"


def _evaluar(vecs):
    """(% el usuario reconocido, % eco tomado por el usuario) dejando fuera cada archivo."""
    d = {"usuario": [], "eco": []}
    for et in d:
        for i, (_, hs) in enumerate(vecs[et]):
            r = {k: [x for j, (_, xs) in enumerate(vecs[k]) for x in xs if not (k == et and j == i)]
                 for k in d}
            pj, pe = _perfil(r["usuario"]), _perfil(r["eco"])
            d[et] += [float(x @ pj - x @ pe) for x in hs]
    j, e = np.array(d["usuario"]), np.array(d["eco"])
    global ULTIMA_METRICA
    ULTIMA_METRICA = {"eer": _eer(j, e), "separacion": float(j.mean() - e.mean()),
                      "ventanas_usuario": int(len(j)), "ventanas_eco": int(len(e))}
    return float((j > 0).mean()), float((e > 0).mean())


ULTIMA_METRICA = {}
HISTORIAL = RAIZ / "aprendizaje_historial.jsonl"  # una línea por pasada (resumen_aprendizaje.py)


def _eer(j, e):
    """Tasa de error igual: el % de fallos cuando se confunden igual el usuario y eco."""
    mejor = (2.0, 1.0)
    for u in np.unique(np.concatenate([j, e])):
        far, frr = float((e >= u).mean()), float((j < u).mean())
        if abs(far - frr) < mejor[0]:
            mejor = (abs(far - frr), (far + frr) / 2)
    return mejor[1]


def _reetiquetar(nombre, nueva):
    """Cambia la etiqueta en el índice y en el nombre del wav (así la limpieza del
    dictado no borra nunca las muestras del usuario)."""
    viejo = MUESTRAS / f"{nombre}.wav"
    base = nombre.rsplit("_", 1)[0]
    nuevo = f"{base}_{nueva}"
    if viejo.exists():
        viejo.rename(MUESTRAS / f"{nuevo}.wav")
    idx = MUESTRAS / "indice.tsv"
    lineas = []
    for linea in idx.read_text(encoding="utf-8").splitlines():
        c = linea.split("\t")
        if c[0] == nombre:
            c[0], c[1] = nuevo, nueva
        lineas.append("\t".join(c))
    idx.write_text("\n".join(lineas) + "\n", encoding="utf-8")


def aprender(log=print):
    """Promueve frases 'solo' a 'usuario' u 'otros' y reentrena si no empeora."""
    h = Huellas()
    if not h.perfiles:
        log("sin perfiles: primero 'entrenar'")
        return
    cambios = []
    for nombre, et in sorted(etiquetas().items()):
        if et != "solo":
            continue
        hs = [x for x in (h.huella(t) for t in ventanas(leer_wav(MUESTRAS / f"{nombre}.wav")))
              if x is not None]
        if not hs:
            continue
        par = float(np.mean([x @ h.perfiles["usuario"] for x in hs]))
        dif = float(np.mean([x @ h.perfiles["usuario"] - x @ h.perfiles["eco"] for x in hs]))
        if par >= APRENDE_PARECIDO and dif >= APRENDE_DIF:
            cambios.append((nombre, "usuario", par, dif))
        elif par < OTROS_PARECIDO:
            cambios.append((nombre, "otros", par, dif))
        else:
            cambios.append((nombre, "dudoso", par, dif))
    antes = _evaluar(cargar_vectores(h))
    for nombre, nueva, _, _ in cambios:
        _reetiquetar(nombre, nueva)
    vecs = cargar_vectores(h)
    despues = _evaluar(vecs)
    nj = sum(c[1] == "usuario" for c in cambios)
    no = sum(c[1] == "otros" for c in cambios)
    # guarda contra empeorar: si la huella nueva reconoce peor o se confunde más, no se usa
    if despues[0] >= antes[0] - 0.02 and despues[1] <= antes[1] + 0.01:
        np.savez(PERFILES, usuario=_perfil([x for _, xs in vecs["usuario"] for x in xs]),
                 eco=_perfil([x for _, xs in vecs["eco"] for x in xs]))
        estado = "perfiles actualizados"
    else:
        estado = "perfiles SIN cambiar (empeoraba)"
    linea = (f"{time.strftime('%Y-%m-%d %H:%M')} +{nj} usuario, +{no} otros, "
             f"{len(cambios) - nj - no} dudosas | el usuario {antes[0]:.0%}->{despues[0]:.0%}, "
             f"eco->el usuario {antes[1]:.0%}->{despues[1]:.0%} | {estado}")
    with open(REGISTRO, "a", encoding="utf-8") as f:
        f.write(linea + "\n")
    try:
        import json
        with open(HISTORIAL, "a", encoding="utf-8") as f:
            f.write(json.dumps({"fecha": time.strftime("%Y-%m-%d %H:%M"), "usuario": despues[0],
                                "eco": despues[1], "nuevas_usuario": nj, "nuevas_otros": no,
                                **ULTIMA_METRICA}) + "\n")
    except OSError:
        pass
    log(linea)


if __name__ == "__main__":
    orden = sys.argv[1] if len(sys.argv) > 1 else "medir"
    if orden == "entrenar":
        entrenar()
    elif orden == "medir":
        medir()
    elif orden == "aprender":
        aprender()
    elif orden == "probar":
        print(Huellas().parecidos(leer_wav(sys.argv[2])))
