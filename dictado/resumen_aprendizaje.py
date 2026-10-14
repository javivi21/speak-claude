"""Cuánto ha aprendido hoy la huella de voz del usuario (para decírselo al cerrar sesión).

  .venv\\Scripts\\python.exe resumen_aprendizaje.py            # hoy
  .venv\\Scripts\\python.exe resumen_aprendizaje.py 2026-10-03 # ese día

Lee aprendizaje_historial.jsonl (una línea por pasada de voz_usuario.aprender, desde el
03-oct-2026) y compara la primera pasada del día con la última, más una medición de
ahora mismo. La métrica que importa es el EER (error cuando el usuario y el eco se confunden
igual): el % de "el usuario reconocido" ya está en 100 % y no puede subir más.
"""
import json
import sys
import time
from pathlib import Path

import voz_usuario

RAIZ = Path(__file__).parent


def main():
    dia = sys.argv[1] if len(sys.argv) > 1 else time.strftime("%Y-%m-%d")
    filas = []
    if voz_usuario.HISTORIAL.exists():
        for linea in voz_usuario.HISTORIAL.read_text(encoding="utf-8").splitlines():
            try:
                f = json.loads(linea)
            except ValueError:
                continue
            if f.get("fecha", "").startswith(dia):
                filas.append(f)
    h = voz_usuario.Huellas()
    voz_usuario._evaluar(voz_usuario.cargar_vectores(h))
    ahora = voz_usuario.ULTIMA_METRICA
    if not filas:
        print(f"{dia}: sin pasadas de aprendizaje registradas. Ahora: EER {ahora['eer']:.1%}.")
        return
    a, b = filas[0], filas[-1]
    nj = sum(f.get("nuevas_usuario", 0) for f in filas)
    no = sum(f.get("nuevas_otros", 0) for f in filas)
    eer0, eer1 = a.get("eer"), ahora["eer"]
    mejora = (eer0 - eer1) / eer0 * 100 if eer0 else 0.0
    print(f"Aprendizaje de voz {dia}: {len(filas)} pasadas, {nj} frases tuyas nuevas, "
          f"{no} ajenas apartadas.")
    print(f"  error (EER): {eer0:.1%} -> {eer1:.1%}  ({mejora:+.0f} % de mejora)")
    sep0 = f"{a['separacion']:.3f}" if a.get("separacion") is not None else "sin medir"
    print(f"  eco tomado por ti (margen 0): {a['eco']:.1%} -> {b['eco']:.1%}; "
          f"separación tú/eco: {sep0} -> {ahora['separacion']:.3f}")
    print(f"  muestras de tu voz: {a.get('ventanas_usuario')} -> {ahora['ventanas_usuario']} ventanas de 2 s")


if __name__ == "__main__":
    main()
