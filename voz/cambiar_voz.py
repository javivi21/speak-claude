"""Cambia la voz de Jarvis entre la masculina (original) y la femenina.

    .venv\\Scripts\\python.exe cambiar_voz.py femenina     # también: masculina, logo, F, M, L
    .venv\\Scripts\\python.exe cambiar_voz.py alternar     # pasa a la siguiente (M, F, L)
    .venv\\Scripts\\python.exe cambiar_voz.py              # dice cuál está activa

Funciona con el servidor encendido o apagado (se guarda en voces.json) y dice una
frase con la voz elegida para que se oiga el cambio.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import leer_ultima as l
import voces


def main():
    cual = sys.argv[1] if len(sys.argv) > 1 else None
    if cual and cual.lower() in ("alternar", "otra", "cambiar"):  # M -> F -> L -> M
        orden = list(voces.cargar()["voces"])
        cual = orden[(orden.index(voces.actual()) + 1) % len(orden)]
    if cual:
        n = voces.fijar(cual)
        if not n:
            print("voz desconocida; usa masculina o femenina")
            sys.exit(1)
    n = voces.actual()
    nombre = voces.cargar()["voces"][n]["nombre"]
    print(f"VOZ ACTIVA: {n} ({nombre})")
    if cual:
        l.pedir_al_servidor({"cmd": "hablar", "texto": f"Vale, ya está. Ahora hablo con la voz {nombre.split()[0]}."})


if __name__ == "__main__":
    main()
