"""Voz de ElevenLabs (Daniel) para el servidor de voz, con Piper de respaldo.

Se configura en eleven.json:  {"activo": true, "voz": "<voice_id>", "modelo": "..."}
Apagar ElevenLabs y volver a Piper: poner "activo": false (se lee en cada frase).
La clave NO se guarda aquí: se busca en la variable ELEVENLABS_API_KEY o en la línea
ELEVENLABS_API_KEY=... de voz\\.env.
Pide el audio en PCM a la misma frecuencia que Piper (22050 Hz), así la salida de
audio del servidor no tiene que reabrirse ni remuestrear.
"""
import json
import os
import urllib.request
from pathlib import Path

import numpy as np

import pronunciacion

RAIZ = Path(__file__).parent
CONFIG = RAIZ / "eleven.json"
ENVS = [RAIZ / ".env"]
TROZO = 4410  # bytes por trozo leído (~0,1 s de PCM 16 bits a 22050 Hz)


def config():
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"activo": False}


def clave():
    if os.environ.get("ELEVENLABS_API_KEY"):
        return os.environ["ELEVENLABS_API_KEY"].strip()
    for env in ENVS:
        try:
            for linea in env.read_text(encoding="utf-8-sig").splitlines():
                if linea.strip().startswith("ELEVENLABS_API_KEY="):
                    valor = linea.split("=", 1)[1].strip().strip('"').strip("'")
                    if valor:
                        return valor
        except OSError:
            continue
    return None


def activo():
    return bool(config().get("activo")) and clave() is not None


def frases(texto, sr=22050):
    """Generador de trozos (audio float32,) que van llegando por streaming.

    Lanza excepción si la petición falla ANTES del primer trozo (para caer a Piper);
    un corte a mitad solo termina la lectura.
    """
    cfg = config()
    url = (f"https://api.elevenlabs.io/v1/text-to-speech/{cfg['voz']}/stream"
           f"?output_format=pcm_{sr}")
    cuerpo = {"text": pronunciacion.para_eleven(texto), "model_id": cfg.get("modelo", "eleven_flash_v2_5"),
              "language_code": "es"}
    if cfg.get("ajustes"):
        cuerpo["voice_settings"] = cfg["ajustes"]
    pet = urllib.request.Request(url, data=json.dumps(cuerpo).encode(), method="POST",
                                 headers={"xi-api-key": clave(),
                                          "content-type": "application/json"})
    resp = urllib.request.urlopen(pet, timeout=float(cfg.get("espera", 6)))
    resto = b""
    with resp:
        while True:
            datos = resp.read(TROZO)
            if not datos:
                break
            datos = resto + datos
            par = len(datos) - len(datos) % 2  # muestras de 16 bits: nunca partir una
            resto = datos[par:]
            if par:
                audio = np.frombuffer(datos[:par], dtype="<i2").astype("float32") / 32768
                yield (audio * float(cfg.get("volumen", 1.0)),)
