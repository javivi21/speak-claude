"""Diagnóstico rápido de la voz de Claude (sin hablar en voz alta ni gastar saldo).

  .venv\\Scripts\\python.exe diagnostico.py

Mira, en este orden: servidor de voz (ping, motor, voz), ElevenLabs (activo, clave,
saldo de caracteres), dictado (proceso vivo, estado, recuento de eco/descartes/fugas
del log), huella de voz (fecha de perfiles, último aprendizaje), Ollama (para el banco)
y la GPU. Cada línea empieza por OK, AVISO o FALLO. Idea sacada de los paneles
el diagnóstico de otro proyecto de voz: el silencio siempre tiene una causa.
"""
import json
import re
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import eleven

RAIZ = Path(__file__).parent
DICTADO = RAIZ.parent / "dictado"
avisos = 0


def linea(estado, texto):
    global avisos
    if estado != "OK":
        avisos += 1
    print(f"{estado:<6}{texto}")


def servidor(cmd):
    with socket.create_connection(("127.0.0.1", 50321), timeout=2) as s:
        s.sendall((json.dumps(cmd) + "\n").encode())
        return s.recv(500).decode("utf-8", "replace").strip()


def pid_vivo(pid):
    salida = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                            capture_output=True, text=True, errors="replace").stdout
    return str(pid) in salida


def main():
    # 1. servidor de voz
    try:
        t0 = time.time()
        r = servidor({"cmd": "ping"})
        ms = (time.time() - t0) * 1000
        linea("OK" if r == "ok" else "FALLO", f"servidor de voz: {r} ({ms:.0f} ms)")
        linea("OK", f"último motor: {servidor({'cmd': 'motor'})} · voz Piper: {servidor({'cmd': 'voz'})}")
    except OSError as e:
        linea("FALLO", f"servidor de voz no responde ({type(e).__name__}): 'arranca la voz de Claude'")
    if (RAIZ / "SILENCIO").exists():
        linea("AVISO", "archivo SILENCIO presente: la voz está silenciada")

    # 2. ElevenLabs
    cfg = eleven.config()
    clave = eleven.clave()
    if not cfg.get("activo"):
        linea("AVISO", "ElevenLabs desactivado en eleven.json: suena Piper")
    elif not clave:
        linea("FALLO", "ElevenLabs activo pero sin clave (.env): cae a Piper")
    else:
        try:
            pet = urllib.request.Request("https://api.elevenlabs.io/v1/user/subscription",
                                         headers={"xi-api-key": clave})
            with urllib.request.urlopen(pet, timeout=6) as resp:
                sub = json.loads(resp.read())
            usados, limite = sub.get("character_count", 0), sub.get("character_limit", 0)
            quedan = limite - usados
            estado = "OK" if quedan > 5000 else "AVISO"
            linea(estado, f"ElevenLabs {cfg.get('modelo')}: {usados} de {limite} caracteres "
                          f"usados, quedan {quedan} (plan {sub.get('tier', '?')})")
        except urllib.error.HTTPError as e:
            if e.code == 401:  # clave restringida: solo voz, sin permiso user_read
                linea("AVISO", "ElevenLabs: la clave no puede leer el saldo (falta permiso "
                               "'User: read'); míralo en elevenlabs.io o amplía la clave")
            else:
                linea("AVISO", f"ElevenLabs: no se pudo leer el saldo (HTTP {e.code})")
        except Exception as e:  # red caída...
            linea("AVISO", f"ElevenLabs: no se pudo leer el saldo ({type(e).__name__}: {e})")

    # 3. dictado
    pid_txt = (DICTADO / "dictado.pid").read_text().strip() if (DICTADO / "dictado.pid").exists() else ""
    if pid_txt.isdigit() and pid_vivo(int(pid_txt)):
        linea("OK", f"dictado vivo (PID {pid_txt})")
    else:
        linea("AVISO", "dictado apagado: 'activa modo escucha'")
    log = DICTADO / "dictado.log"
    if log.exists():
        texto = log.read_text(encoding="utf-8", errors="replace")
        cuenta = {k: len(re.findall(rf"\[{k}\]", texto)) for k in
                  ("eco", "descartado", "otra persona", "fin de turno", "el usuario por encima", "corte", "enter perdido", "enviado")}
        linea("OK", "log del dictado: " + ", ".join(f"{k} {v}" for k, v in cuenta.items()))
        if cuenta["enter perdido"]:
            linea("AVISO", "hubo 'enter perdido': el foco no estaba en la ventana de Claude")
        if cuenta["el usuario por encima"]:
            linea("AVISO", "revisar [el usuario por encima]: si no era el usuario es una fuga de eco "
                           "(añadirla a prueba_eco.py)")
    err = DICTADO / "dictado.err"
    if err.exists() and err.stat().st_size:
        linea("AVISO", f"dictado.err tiene {err.stat().st_size} bytes de errores")

    # 4. huella de voz
    perfiles = DICTADO / "perfiles_voz.npz"
    if perfiles.exists():
        edad = (time.time() - perfiles.stat().st_mtime) / 3600
        linea("OK", f"perfiles de huella: hace {edad:.1f} h")
    else:
        linea("AVISO", "sin perfiles de huella: el dictado decide solo por texto")
    apr = DICTADO / "aprendizaje.log"
    if apr.exists():
        ultima = apr.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-1:]
        if ultima:
            linea("AVISO" if "SIN cambiar" in ultima[0] else "OK", f"último aprendizaje: {ultima[0]}")
    cfg_d = json.loads((DICTADO / "config.json").read_text(encoding="utf-8"))
    if cfg_d.get("aprender_voz") is False:
        linea("AVISO", "aprendizaje de voz apagado en config.json")
    linea("OK", f"envío automático tras {cfg_d.get('segundos_para_enviar')} s de silencio")

    # 5. Ollama (solo lo usa el banco de pruebas, niveles 9-10)
    try:
        urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=2).close()
        linea("OK", "Ollama en marcha (banco de pruebas completo posible)")
    except OSError:
        linea("AVISO", "Ollama apagado: pruebas.py --todos se para en el nivel 10")

    # 6. GPU
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total",
                              "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
        usado, total = (int(x) for x in out.split(","))
        linea("OK" if total - usado > 2000 else "AVISO", f"GPU: {usado} de {total} MB en uso")
    except Exception:
        linea("AVISO", "nvidia-smi no disponible")

    print(f"\n{'todo en orden' if not avisos else f'{avisos} aviso(s)'}")


if __name__ == "__main__":
    main()
