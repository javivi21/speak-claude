"""Las dos voces de la voz de Claude (Piper sharvard: masculina y femenina) y cuál está activa.

Se guardan en voces.json, así que el cambio sobrevive a reinicios y lo ven a la vez el
servidor y la CLI de respaldo. Cada voz lleva su estilo (ritmo, variación, pausa...).
"""
import json
from pathlib import Path

ARCHIVO = Path(__file__).parent / "voces.json"

# M = la original del usuario (speaker 0). F = la femenina (speaker 1) con los valores del
# modelo (con length 1,1 / noise 0,8-1,0 le sonaba "muy rara"). L = la femenina con un
# guiño de "píxeles" al logo de Claude: serena y sobria, no de mascota (el usuario, 21-sep).
# Pausa 0,08 s en todas: con 0,22 s el usuario la notaba marcada y robótica.
POR_DEFECTO = {
    "actual": "M",
    "voces": {
        "M": {"nombre": "masculina (original)", "estilo": {"pausa": 0.08}},
        # F elegida por el usuario en la cata de afinado (21-sep): variante "2, estable", con
        # menos variación de entonación (0,55; fábrica 0,667) y de duración (0,65; fábrica 0,8)
        "F": {"nombre": "femenina", "estilo": {"pausa": 0.08, "speaker_id": 1,
                                                "noise_scale": 0.55, "noise_w_scale": 0.65}},
        "L": {"nombre": "logo (femenina con guiño de píxeles)", "estilo": {
            "pausa": 0.08, "speaker_id": 1, "noise_scale": 0.55, "noise_w_scale": 0.65,
            "efectos": {"pixel": {"pasos": 3, "bits": 7, "mezcla": 0.25},
                        "metal": {"ms": 5, "mezcla": 0.15},
                        "reverb": {"seg": 0.2, "mezcla": 0.1}}}},
    },
}
ALIAS = {"m": "M", "masculina": "M", "original": "M", "hombre": "M",
         "f": "F", "femenina": "F", "mujer": "F",
         "l": "L", "logo": "L", "ia": "L", "pixel": "L", "claude": "L"}


def cargar():
    try:
        datos = json.loads(ARCHIVO.read_text(encoding="utf-8"))
        if datos.get("actual") in datos.get("voces", {}) and datos["voces"]:
            return datos
    except (OSError, ValueError, AttributeError):
        pass
    return json.loads(json.dumps(POR_DEFECTO))  # copia: nunca se toca el original


def nombre_valido(cual):
    cual = ALIAS.get(str(cual or "").strip().lower(), str(cual or "").strip().upper())
    return cual if cual in cargar()["voces"] else None


def actual():
    return cargar()["actual"]


def estilo(cual=None):
    datos = cargar()
    return datos["voces"].get(nombre_valido(cual) or datos["actual"], {}).get("estilo", {})


def fijar(cual):
    """Cambia la voz activa. Devuelve el nombre (M/F) o None si no existe."""
    n = nombre_valido(cual)
    if not n:
        return None
    datos = cargar()
    datos["actual"] = n
    ARCHIVO.write_text(json.dumps(datos, indent=2, ensure_ascii=False), encoding="utf-8")
    return n
