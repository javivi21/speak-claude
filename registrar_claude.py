"""Conecta Claude Code con speak-claude: añade los hooks y el aviso para el resumen hablado.

Lo lanza instalar.ps1. Es seguro repetirlo: no duplica nada y antes guarda una copia de tus archivos
(settings.json.bak-speak-claude). Para quitarlo, borra las entradas que mencionan speak-claude.
Uso: python registrar_claude.py <carpeta-del-repo>
"""
import json
import shutil
import sys
from pathlib import Path

MARCA = "speak-claude"
BLOQUE = f"""
<!-- {MARCA}:inicio -->
# Voz de Claude ({MARCA})
Al final de CADA respuesta, añade una última línea `VOZ: <resumen>`: una o dos frases de charla natural,
sin rutas, archivos, símbolos, números de línea ni jerga técnica. Esa línea es la que se lee en voz alta.
<!-- {MARCA}:fin -->
"""


def main(repo):
    raiz = Path(repo).resolve()
    py = (raiz / "voz" / ".venv" / "Scripts" / "python.exe").as_posix()
    lector = (raiz / "voz" / "leer_ultima.py").as_posix()
    arrancar = str(raiz / "voz" / "arrancar.ps1")
    home = Path.home() / ".claude"
    home.mkdir(exist_ok=True)

    cfg_ruta = home / "settings.json"
    cfg = json.loads(cfg_ruta.read_text(encoding="utf-8")) if cfg_ruta.exists() else {}
    if cfg_ruta.exists():
        shutil.copy2(cfg_ruta, home / "settings.json.bak-speak-claude")
    hooks = cfg.setdefault("hooks", {})

    def poner(evento, entrada):
        lista = hooks.setdefault(evento, [])
        if not any(MARCA in json.dumps(x) or lector in json.dumps(x) or arrancar.replace("\\", "\\\\") in json.dumps(x)
                   for x in lista):
            lista.append(entrada)

    poner("Stop", {"hooks": [{"type": "command", "command": f"{py} {lector}", "timeout": 10}]})
    poner("SessionStart", {"hooks": [{
        "type": "command", "shell": "powershell", "timeout": 60, "async": True,
        "statusMessage": "Arrancando la voz de Claude...",
        "command": f"powershell -NoProfile -ExecutionPolicy Bypass -File '{arrancar}' -Silencioso | Out-Null"}]})
    cfg_ruta.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    md = home / "CLAUDE.md"
    actual = md.read_text(encoding="utf-8") if md.exists() else ""
    if f"{MARCA}:inicio" not in actual:
        if md.exists():
            shutil.copy2(md, home / "CLAUDE.md.bak-speak-claude")
        md.write_text(actual.rstrip() + "\n" + BLOQUE, encoding="utf-8")
    print("Claude Code conectado.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
