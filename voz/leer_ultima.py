"""Hook 'Stop' de Claude Code: lee en voz alta la última respuesta.

Por defecto habla un RESUMEN: si la respuesta acaba en una línea 'VOZ: ...' se lee
esa; si no, se resume el texto quitando código, rutas y símbolos.

Modo textual (lee sin resumir la respuesta N-ésima anterior, 1 = la última):
    .venv\\Scripts\\python.exe leer_ultima.py --textual <transcript.jsonl> [N]

La voz se pide al servidor residente (servidor_voz.py), que tiene Piper ya cargado;
si no está en marcha se arranca y esta vez se usa hablar.py directamente.
Silenciar: crear el archivo  voz\\SILENCIO  (borrarlo para reactivar).
"""
import json
import re
import socket
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).parent
PY = RAIZ / ".venv" / "Scripts" / "python.exe"
PYW = RAIZ / ".venv" / "Scripts" / "pythonw.exe"
PUERTO = 50321
MAX_CARACTERES = 320  # resumen hablado: corto, pero con lo importante dentro
MAX_TEXTUAL = 3000  # resumen hablado
MAX_LECTURA = 20000  # modo textual: respuesta entera
LOG_MAX = 200  # líneas que se conservan en hook.log
ETIQUETA = re.compile(r"^\s*VOZ:\s*(.+)$", re.M)
SIN_CONSOLA = 0x00000008 | 0x00000200  # DETACHED_PROCESS | NEW_PROCESS_GROUP


# --- lectura del transcript -------------------------------------------------

def textos_asistente(transcript):
    """Todos los textos del asistente, en orden."""
    res = []
    try:
        with open(transcript, encoding="utf-8") as f:
            for linea in f:
                try:
                    o = json.loads(linea)
                except ValueError:
                    continue
                if o.get("type") != "assistant":
                    continue
                cont = (o.get("message") or {}).get("content")
                t = cont if isinstance(cont, str) else "\n".join(
                    b.get("text", "") for b in cont or [] if b.get("type") == "text")
                if t.strip():
                    res.append(t)
    except OSError:
        pass
    return res


# --- limpieza del texto -----------------------------------------------------

def limpiar_base(t, corte=True):
    """Quita markdown, código, enlaces y emojis; deja algo pronunciable."""
    t = re.sub(r"```.*?```", " ", t, flags=re.S)
    t = re.sub(r"`([^`]*)`", r"\1", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"https?://\S+", "", t)
    t = "\n".join(l for l in t.splitlines()
                  if not re.match(r"^\s*\|", l) and not re.match(r"^\s*[-=*_]{3,}\s*$", l))
    t = re.sub(r"^\s{0,3}#{1,6}\s*", "", t, flags=re.M)
    t = re.sub(r"[*_>#~]", "", t)
    t = re.sub(r"^\s*[-•]\s+", "", t, flags=re.M)
    t = re.sub(r"[A-Za-z]:\\[^\s]+", "", t)
    t = re.sub(r"~?(?:\\[\w.\-]+)+\\?", " ", t)  # rutas sin unidad: ~\.claude\skills\
    t = re.sub(r"[\U0001F300-\U0001FAFF☀-➿]", "", t)
    t = re.sub(r"\s*\n+\s*", ". ", t)
    t = re.sub(r"\.\s*\.", ".", t)
    t = re.sub(r"\s+", " ", t).strip()
    if corte and len(t) > MAX_CARACTERES:
        pos = t.rfind(". ", 0, MAX_CARACTERES)
        t = t[: pos + 1] if pos > 120 else t[:MAX_CARACTERES]
    return t


def resumen_hablado(bruto):
    """Resumen natural: usa la línea 'VOZ: ...' si existe; si no, aligera el texto."""
    etiquetas = [e for e in ETIQUETA.findall(bruto) if e.strip()]
    if etiquetas:  # una etiqueta vacía no vale: se sigue al resumen automático
        # también se limpia: si en la línea VOZ: se cuela un enlace, una ruta o
        # código, se leería deletreado ("hache te te pe dos puntos barra barra")
        dicho = sin_jerga(limpiar_base(etiquetas[-1], corte=False))
        dicho = re.sub(r"\bVOZ\b:?", " ", dicho)  # etiquetas repetidas dentro
        dicho = re.sub(r"\s+", " ", dicho).strip(" .,")
        if len(dicho) > MAX_TEXTUAL:
            dicho = dicho[:MAX_TEXTUAL].rsplit(" ", 1)[0]
        if len(dicho) > 8:
            return dicho if dicho.endswith(("!", "?")) else dicho + "."
    limpio = limpiar_base(ETIQUETA.sub("", bruto), corte=False)
    frases = []
    for frase in re.split(r"(?<=[.!?])\s+", limpio):
        antes = len(re.findall(r"\w+", frase))
        hablada = sin_jerga(frase)
        # una frase a la que le falten palabras suena entrecortada: se descarta
        if antes and len(re.findall(r"\w+", hablada)) >= 0.7 * antes and len(hablada) > 12:
            frases.append(hablada)
    # se van juntando frases enteras hasta llenar el presupuesto: cortar a dos
    # fijas dejaba fuera lo importante en las respuestas largas
    salida = ""
    for frase in frases:
        if salida and len(salida) + 1 + len(frase) > MAX_CARACTERES:
            break
        salida = f"{salida} {frase}".strip()
    salida = salida.strip(" .,")
    if len(salida) > MAX_CARACTERES:
        corte = salida[:MAX_CARACTERES]
        # se corta en el último límite de cláusula (coma, punto y coma, dos
        # puntos), no a mitad de frase ("... estructurado por")
        pos = max(corte.rfind(", "), corte.rfind("; "), corte.rfind(": "))
        salida = (corte[:pos] if pos > 0.5 * MAX_CARACTERES
                  else corte.rsplit(" ", 1)[0]).strip(" .,;:")
    if len(salida) <= 8:
        return "Hecho. Mira la pantalla."
    return salida if salida.endswith(("!", "?")) else salida + "."


def hora_hablada(m):
    """21:12 -> '21 y 12'; 21:00 -> '21 en punto'. Si no, sonaría a decimal."""
    h, mi = m.group(1), m.group(2)
    return f"{h} en punto" if mi == "00" else f"{h} y {int(mi)}"


def sin_jerga(t):
    """Quita código, rutas, identificadores y números: lo que no se dice hablando."""
    t = re.sub(r"```.*?```", " ", t, flags=re.S)
    t = re.sub(r"`[^`]*`", " ", t)
    t = re.sub(r"\S+\.(py|ps1|md|json|log|txt|js|ts|wav|onnx|exe)(:\d+(-\d+)?)?", " ", t)
    t = re.sub(r"\w*_\w+", " ", t)
    t = re.sub(r"\b[a-z]+[A-Z]\w*", " ", t)  # 05-oct: sin \b dejaba "DeporWeb" en "D"
    t = re.sub(r"\w+\(\)", " ", t)
    t = re.sub(r"\b[0-9a-fx]{6,}\b", " ", t)  # códigos tipo 0x00000008
    # los números normales SÍ se dicen (horas, segundos, cantidades): Piper los lee bien
    t = re.sub(r"\b(\d{1,2}):(\d{2})\b", hora_hablada, t)  # antes de tocar los ':'
    t = re.sub(r"[:;]", ",", t)  # dos puntos y punto y coma: pausa, no hueco mudo
    t = re.sub(r"[()\[\]{}<>=/\\|@#$%^&*_~\"“”]", " ", t)
    t = re.sub(r"\s+([.,])", r"\1", t)
    t = re.sub(r",\s*,", ",", t)
    return re.sub(r"\s+", " ", t).strip(" ,")


def texto_textual(bruto):
    """Texto casi íntegro: sin código ni símbolos, pero sin resumir."""
    t = limpiar_base(ETIQUETA.sub("", bruto), corte=False)
    t = re.sub(r"[:;()\[\]{}<>=/\\|@#$%^&*~\"“”]", " ", t)
    return re.sub(r"\s+", " ", t).strip()[:MAX_LECTURA]


# --- reproducción -----------------------------------------------------------

def pedir_al_servidor(peticion, timeout=20):
    """Devuelve la respuesta del servidor residente, o None si no está."""
    try:
        with socket.create_connection(("127.0.0.1", PUERTO), timeout=1.5) as s:
            s.settimeout(timeout)
            # el salto de línea marca el final: el servidor lee hasta encontrarlo
            s.sendall(json.dumps(peticion).encode() + b"\n")
            resp = s.recv(1024).decode("utf-8", "replace").strip()
            return resp or None  # respuesta vacía = no atendido
    except OSError:
        return None


def arrancar_servidor():
    exe = PYW if PYW.exists() else PY
    try:
        subprocess.Popen([str(exe), str(RAIZ / "servidor_voz.py")], creationflags=SIN_CONSOLA,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, close_fds=True)
    except OSError:
        pass


def hablar_suelto(texto):
    """Respaldo sin servidor: un proceso por frase (paga la carga del modelo)."""
    try:
        subprocess.Popen(
            [str(PY), str(RAIZ / "hablar.py"), "--motor", "piper", "--voz", "sharvard", texto],
            creationflags=SIN_CONSOLA, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, close_fds=True)
    except OSError:
        pass


def decir(texto, prioridad=False):
    peticion = {"cmd": "hablar", "texto": texto, "prioridad": prioridad}
    if pedir_al_servidor(peticion) is not None:
        return
    arrancar_servidor()
    # se espera a que cargue el modelo: así dos respuestas seguidas van las dos por
    # el servidor, que sabe encadenarlas, en vez de solaparse dos voces sueltas
    import time

    for _ in range(8):  # el hook tiene 10 s de límite: con 16 lo mataban antes del respaldo
        time.sleep(1)
        if pedir_al_servidor(peticion) is not None:
            return
    hablar_suelto(texto)  # no arrancó: al menos que se oiga


# --- entradas ---------------------------------------------------------------

def textual(transcript, atras=1):
    textos = textos_asistente(transcript)
    if len(textos) < atras or atras < 1:
        return
    t = texto_textual(textos[-atras])
    if len(t) > 2:
        decir(t, prioridad=True)


def registrar(mensaje):
    import datetime

    ruta = RAIZ / "hook.log"
    linea = f"{datetime.datetime.now().isoformat(timespec='seconds')} {mensaje}\n"
    try:
        previas = ruta.read_text(encoding="utf-8").splitlines(keepends=True)[-LOG_MAX:]
    except OSError:
        previas = []
    try:
        ruta.write_text("".join(previas) + linea, encoding="utf-8")
    except OSError:
        pass


def main():
    registrar("hook disparado")
    pedir_al_servidor({"cmd": "espera", "tras": 0}, timeout=2)  # turno acabado: sin frase de espera
    if (RAIZ / "SILENCIO").exists():
        return
    try:
        datos = json.load(sys.stdin)
    except ValueError:
        return
    ruta = datos.get("transcript_path")
    if not ruta:
        return
    textos = textos_asistente(ruta)
    if not textos:
        return
    texto = resumen_hablado(textos[-1])
    if len(texto) > 2:
        if repetida(texto):
            registrar(f"repetida, no se dice: {texto[:60]}")
            return
        registrar(f"dice: {texto[:60]}")
        decir(texto)


def repetida(texto, ventana=600):
    """03-oct 18:45: el usuario oía las frases DOS veces. Si Stop salta otra vez sin respuesta
    nueva (otro hook que hace seguir el turno, mensaje a mitad de turno), el último texto
    es el mismo y se volvía a leer. Misma frase en los últimos 10 min = no se repite."""
    import hashlib
    import time

    ruta = RAIZ / "ULTIMA_LEIDA"
    h = hashlib.sha1(texto.encode("utf-8")).hexdigest()
    try:
        previo, cuando = ruta.read_text(encoding="utf-8").split()
        if previo == h and time.time() - float(cuando) < ventana:
            return True
    except (OSError, ValueError):
        pass
    try:
        ruta.write_text(f"{h} {time.time()}", encoding="utf-8")
    except OSError:
        pass
    return False


if __name__ == "__main__":
    if "--textual" in sys.argv:
        args = sys.argv[sys.argv.index("--textual") + 1:]
        if not args:
            sys.exit("uso: leer_ultima.py --textual <transcript.jsonl> [N]")
        try:
            atras = int(args[1]) if len(args) > 1 else 1
        except ValueError:
            atras = 1  # un N que no es número: se lee la última respuesta
        textual(args[0], atras)
    else:
        main()
