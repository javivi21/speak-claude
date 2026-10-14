"""Mientras Claude trabaja: narración de lo que va haciendo + relleno si hay silencio.

Idea de otro proyecto de voz (habla mientras Claude escribe), adaptada
a Claude Code el 03-oct-2026 tras quejarse el usuario de que "dame un momento" / "voy con
ello" sonaban repetitivas y luego el momento se hacía eterno.

Hooks (en ~/.claude/settings.json):
    UserPromptSubmit -> espera.py inicio       empieza el turno: el servidor dirá una
                                               frase de RELLENO a los ESPERA_TRAS s si
                                               nadie ha hablado (máx. 3, nunca repetida)
    PreToolUse       -> espera.py herramienta  NARRACIÓN: lee del transcript el último
                                               texto que Claude escribió antes de usar
                                               la herramienta y lo dice (sin pisar lo
                                               que suena; si llegan varios, el último)
    Stop (leer_ultima.py)                      fin de turno: cancela todo y dice el VOZ:
Las frases de relleno están ya sintetizadas en cache_espera/ (suenan al instante).
Silencio total: archivo SILENCIO. Solo sin narración: archivo SIN_NARRACION.
"""
import json
import re
import socket
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).parent
INICIO = RAIZ / "ESPERA_INICIO"  # cuándo empezó el turno actual
DICHA = RAIZ / "ESPERA_DICHA"  # (antiguo) ya no se usa: lo lleva el servidor
ESPERA_TRAS = 2.5  # s tras el mensaje del usuario: primero un "te he oído" corto
PUERTO = 50321
NARRACION_MAX = 170  # caracteres por paso narrado: una o dos frases cortas

# Primer relleno de cada turno: "te he oído", corto, dictado por el usuario (03-oct). Según
# el mensaje: a una ORDEN se contesta "ok, voy"; a una PREGUNTA, "a ver, lo miro".
FRASES_ORDEN = [
    "Ok, voy.",
    "Vale, voy.",
    "¡Vamos!",
    "Venga, voy.",
    "Tranqui, que voy.",
    "Venga, ya lo hago.",
    "Voy a ello.",
    "Vale.",
]
FRASES_PREGUNTA = [
    "A ver...",
    "Espera.",
    "Espera, que miro.",
    "Voy a ver.",
    "Voy a echar un ojo.",
    "Compruebo.",
    "Voy a echar un ojo, que no sé cómo está la cosa.",
    "Voy a comprobarlo.",
    "Lo miro y te digo.",
    "Deja que lo mire.",
    "Mmm... voy a echar un ojo.",
]
FRASES_INICIO = FRASES_ORDEN + FRASES_PREGUNTA

_PREGUNTA = re.compile(
    r"^\W*(?:y\s+|pero\s+|oye,?\s+|vale,?\s+)?(?:qu[eé]|c[oó]mo|cu[aá]l|cu[aá]nt|por\s?qu[eé]|"
    r"d[oó]nde|cu[aá]ndo|qui[eé]n|puedes|podr[ií]as|sabes|te\s+parece|hay\s+(?!que)|"
    r"es\s|est[aá]s?\s|tienes|funciona|quieres|has\s|vas\s+a)", re.IGNORECASE)


def tipo_mensaje(texto):
    """'pregunta' si el usuario pregunta algo; si no, 'orden' (también vale para "suena bien")."""
    texto = (texto or "").strip()
    if "?" in texto or _PREGUNTA.search(texto):
        return "pregunta"
    return "orden"


# Relleno: solo suena si hay silencio largo (la narración va primero). Al estilo de
# el usuario, variadas, sin "voy con ello" / "dame un momento" (03-oct: "no me gusta nada").
# el usuario puede dictar más: añadirlas aquí; el servidor las sintetiza y guarda solo.
FRASES = [
    "A ver, esto tiene miga.",
    "Esto lleva un poquito más.",
    "Sigo aquí, no me he ido.",
    "Va saliendo, espera.",
    "Casi lo tengo.",
    "Estoy comprobando que funcione.",
    "Esto es más largo de lo que parecía.",
    "Ahora mismo te cuento.",
    "Me está costando un poco, pero va.",
    "Un poco de paciencia, que esto va largo.",
]
TODAS = FRASES_INICIO + FRASES


def pedir(peticion):
    try:
        with socket.create_connection(("127.0.0.1", PUERTO), timeout=1) as s:
            s.settimeout(2)
            s.sendall(json.dumps(peticion).encode() + b"\n")
            s.recv(64)
    except OSError:
        pass  # sin servidor no se dice nada: ni el relleno ni la narración son imprescindibles


def ultimo_texto_del_turno(transcript):
    """Último bloque de texto del asistente desde el último mensaje real del usuario."""
    ultimo = None
    try:
        with open(transcript, encoding="utf-8") as f:
            for linea in f:
                try:
                    o = json.loads(linea)
                except ValueError:
                    continue
                cont = (o.get("message") or {}).get("content")
                if o.get("type") == "user":
                    # un resultado de herramienta no es un mensaje del usuario
                    es_resultado = isinstance(cont, list) and any(
                        isinstance(b, dict) and b.get("type") == "tool_result" for b in cont)
                    if not es_resultado:
                        ultimo = None
                elif o.get("type") == "assistant" and isinstance(cont, list):
                    t = "\n".join(b.get("text", "") for b in cont
                                  if isinstance(b, dict) and b.get("type") == "text")
                    if t.strip():
                        ultimo = t
    except OSError:
        return None
    return ultimo


def hablado(texto):
    """Lo pronunciable de un paso intermedio: sin código, rutas ni símbolos, corto."""
    if re.search(r"^\s*VOZ:", texto, re.M):
        return ""  # eso es el final de la respuesta: lo dice el hook Stop
    from leer_ultima import limpiar_base, sin_jerga
    t = sin_jerga(limpiar_base(texto, corte=False))
    salida = ""
    for frase in re.split(r"(?<=[.!?])\s+", t):
        if salida and len(salida) + len(frase) + 1 > NARRACION_MAX:
            break
        salida = f"{salida} {frase}".strip()
    salida = salida[:NARRACION_MAX].strip(" ,;:")
    return salida if len(re.findall(r"\w+", salida)) >= 3 else ""


def main():
    modo = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        datos = json.loads(sys.stdin.read() or "{}")
    except Exception:
        datos = {}
    if modo == "inicio":
        INICIO.write_text(str(time.time()))
        pedir({"cmd": "espera", "tras": ESPERA_TRAS, "tipo": tipo_mensaje(datos.get("prompt"))})
    elif modo == "herramienta":
        if (RAIZ / "SILENCIO").exists() or (RAIZ / "SIN_NARRACION").exists():
            return
        ruta = datos.get("transcript_path")
        texto = hablado(ultimo_texto_del_turno(ruta) or "") if ruta else ""
        if texto:
            pedir({"cmd": "narrar", "texto": texto})


if __name__ == "__main__":
    main()
