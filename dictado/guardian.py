"""Vigilante del dictado: F9 lo vuelve a levantar aunque se cerrara con F10.

Proceso mínimo (solo escucha el teclado, sin modelo ni micrófono). Mientras el dictado
está vivo no hace nada: F9 lo gestiona el propio dictado (pausa/reanuda). Si el
dictado está cerrado, F9 lo arranca con activar.ps1 y suena un pitido grave
("voy cargando"); a los ~35 s el dictado da su doble pitido de ESCUCHANDO.

Lo lanza activar.ps1 (uno solo: guardian.pid). Se cierra con parar.ps1 -Todo.
Creado el 03-oct-2026: el usuario hablaba con el dictado cerrado y la voz de Claude
contestaba pero no le oía.
"""
import os
import subprocess
import sys
import time
import winsound
from pathlib import Path

from pynput.keyboard import Key, Listener

RAIZ = Path(__file__).parent
PID_DICTADO = RAIZ / "dictado.pid"
PID_PROPIO = RAIZ / "guardian.pid"
ACTIVAR = RAIZ / "activar.ps1"
SIN_CONSOLA = 0x08000000

ultimo = [0.0]


def dictado_vivo():
    try:
        pid = int(PID_DICTADO.read_text().strip())
    except (OSError, ValueError):
        return False
    salida = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True,
                            text=True, errors="replace", creationflags=SIN_CONSOLA).stdout
    return str(pid) in salida


def al_pulsar(tecla):
    if tecla != Key.f9 or time.time() - ultimo[0] < 5:
        return
    ultimo[0] = time.time()
    if dictado_vivo():
        return  # el dictado se encarga de su F9
    winsound.Beep(440, 250)
    subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                      str(ACTIVAR), "-SinGuardian"], creationflags=SIN_CONSOLA,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)


def main():
    # Instancia unica (05-oct): varios activar.ps1 a la vez dejaban tres vigilantes.
    import ctypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _mutex = k32.CreateMutexW(None, False, "Local\\GuardianDictadoClaude")
    if ctypes.get_last_error() == 183:
        return 0
    PID_PROPIO.write_text(str(os.getpid()))
    with Listener(on_press=al_pulsar) as escucha:
        escucha.join()


if __name__ == "__main__":
    sys.exit(main())
