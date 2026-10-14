"""Asistente de ElevenLabs: valida la clave, deja escuchar varias voces y guarda la elegida.

Lo lanza instalar.ps1 con la clave en la variable de entorno ELEVENLABS_API_KEY (no por línea de
comandos). Guarda la clave en voz/.env (ignorado por git) y la voz en voz/eleven.json.
También se puede ejecutar a mano:  .venv\\Scripts\\python.exe configurar_eleven.py
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
import sounddevice as sd

RAIZ = Path(__file__).parent
API = "https://api.elevenlabs.io/v1"
MODELO = "eleven_flash_v2_5"
FRASE = "Hola, soy tu asistente. Así sueno."
SR = 22050
MAX_VOCES = 8


def pedir(ruta, clave, cuerpo=None):
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    pet = urllib.request.Request(f"{API}{ruta}", data=datos, method="POST" if datos else "GET",
                                 headers={"xi-api-key": clave, "content-type": "application/json"})
    return urllib.request.urlopen(pet, timeout=20)


def validar(clave):
    """None si la clave sirve; si no, el motivo en una frase."""
    try:
        with pedir("/voices", clave) as r:
            r.read(1)
        return None
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return ("ElevenLabs no acepta esa clave. Al crearla, deja activados todos los permisos "
                    "(o al menos 'Text to Speech' y 'Voices: lectura') y cópiala entera.")
        return f"ElevenLabs respondió con el error {e.code}."
    except OSError:
        return "No he podido conectar con ElevenLabs. Revisa tu conexión a internet."


def voces(clave):
    with pedir("/voices", clave) as r:
        todas = json.loads(r.read().decode())["voices"]
    base = [v for v in todas if v.get("category") == "premade"] or todas
    return base[:MAX_VOCES]


def decir(clave, voz_id, texto=FRASE):
    """Reproduce el texto con esa voz. False si ElevenLabs no la deja usar (plan, permisos)."""
    cuerpo = {"text": texto, "model_id": MODELO, "language_code": "es"}
    try:
        with pedir(f"/text-to-speech/{voz_id}?output_format=pcm_{SR}", clave, cuerpo) as r:
            pcm = r.read()
    except (urllib.error.HTTPError, OSError):
        return False
    audio = np.frombuffer(pcm[: len(pcm) - len(pcm) % 2], dtype="<i2").astype("float32") / 32768
    sd.play(audio * 0.8, SR)
    sd.wait()
    return True


def guardar(clave, voz):
    (RAIZ / ".env").write_text(f"ELEVENLABS_API_KEY={clave}\n", encoding="utf-8")
    (RAIZ / "eleven.json").write_text(json.dumps({
        "activo": True, "voz": voz["voice_id"], "nombre_voz": f"{voz['name']} (ElevenLabs)",
        "modelo": MODELO, "volumen": 0.8, "espera": 6}, ensure_ascii=False, indent=2), encoding="utf-8")


def etiqueta(v):
    et = v.get("labels") or {}
    extra = ", ".join(x for x in (et.get("gender"), et.get("accent"), et.get("description")) if x)
    return f"{v['name']}" + (f" ({extra})" if extra else "")


def main():
    clave = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not clave:
        print("No he recibido ninguna clave.")
        return 1
    error = validar(clave)
    if error:
        print(error)
        return 2
    print("Clave correcta. Te pongo a escuchar algunas voces (tardan unos segundos cada una).\n")
    lista = voces(clave)
    sonaron = []
    for i, v in enumerate(lista, 1):
        print(f"  {i}) {etiqueta(v)}")
        if decir(clave, v["voice_id"]):
            sonaron.append(i)
            time.sleep(0.4)
        else:
            print("     (esta voz no está disponible con tu plan)")
    if not sonaron:
        print("\nNo he podido reproducir ninguna voz con esta clave; sigo con la voz gratuita.")
        return 3
    while True:
        try:
            r = input(f"\nNúmero de la voz que prefieres [Enter = {sonaron[0]}]: ").strip()
        except EOFError:
            r = ""
        n = int(r) if r.isdigit() else sonaron[0]
        if n in sonaron:
            break
        print("Elige uno de los números que han sonado.")
    guardar(clave, lista[n - 1])
    print(f"Voz guardada: {etiqueta(lista[n - 1])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
