"""Escuchar un audio (vídeo, nota de voz) sin que el dictado lo descarte por no ser el usuario.

  .venv\\Scripts\\python.exe modo_audio.py on    # apaga el filtro de otras personas
  .venv\\Scripts\\python.exe modo_audio.py off   # lo vuelve a encender
  .venv\\Scripts\\python.exe modo_audio.py       # dice cómo está

El dictado relee config.json cada 3 s: no hace falta reiniciarlo.
"""
import json
import sys
from pathlib import Path

CONFIG = Path(__file__).parent / "config.json"

cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
if len(sys.argv) > 1 and sys.argv[1] in ("on", "off"):
    cfg["filtro_otras_personas"] = sys.argv[1] == "off"
    CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("MODO AUDIO: " + ("apagado (filtro activo)" if cfg.get("filtro_otras_personas", True)
                        else "encendido (se transcribe cualquier voz)"))
