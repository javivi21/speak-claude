"""¿Lo que ha oído el micro es Jarvis (eco de los altavoces) o es el usuario?

Idea tomada de otro proyecto de voz (función isEcho): mientras la voz de Claude
habla, el dictado sigue transcribiendo y compara las PALABRAS oídas con el texto que
Jarvis está diciendo (lo escribe servidor_voz.py en la marca HABLANDO). Se compara
como bolsa de palabras y no por parecido de cadenas: Whisper destroza el eco, pero
las palabras sobreviven.

- Palabras de corte ("espera", "para", "calla"...): siempre pasan y callan a Jarvis.
- Coincide con lo que dice Jarvis: eco, se descarta.
- No coincide: es el usuario hablando por encima; se le escucha.

Solo usa la biblioteca estándar: se prueba sin cargar Whisper.
"""
import re
from difflib import SequenceMatcher
import unicodedata

# Cortan aunque Jarvis acabe de decir esa misma palabra: que "para" no calle a
# Jarvis porque él también dijo "para" sería el fallo más irritante posible.
CORTE = re.compile(
    r"\b(para(?:te)?|para ya|espera|calla(?:te)?|basta|silencio|cancela|"
    r"stop|olvidalo|dejalo|vale ya|ya esta bien)\b"
)

# Palabras tan comunes que no prueban nada: "¿y lo segundo?" comparte casi todo con
# cualquier respuesta, y sin esta lista se tiraría como eco una pregunta real.
COMUNES = set((
    "a al ante bajo con contra de del desde en entre hacia hasta para por segun sin "
    "sobre tras el la los las lo un una unos unas y e o u ni que pero mas si no ya "
    "me te se le les nos os mi tu su mis tus sus yo tu el ella nosotros vosotros "
    "ellos ellas es son era fue ser estar esta estan esto eso este ese aqui ahi alli "
    "como cuando donde quien cual muy tambien bien vale pues entonces asi hay ha he "
    "han hemos tiene tengo uno dos tres primero segundo ahora luego otro otra todo "
    "nada algo eh ah oye mira bueno claro"
).split())


INVENTOS = {"gracias", "muchas gracias", "gracias por ver", "musica", "aplausos",
           "risas", "silencio total", "hasta la proxima", "adios"}


def normalizar(texto):
    t = unicodedata.normalize("NFD", (texto or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")  # quita tildes
    t = re.sub(r"[^a-z0-9ñ ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _parecida(palabra, suyas, pegado=""):
    """Whisper cambia terminaciones ("distinguir" -> "distinguirme"): cuenta como la
    misma palabra si es igual o muy parecida a alguna de las que dijo Jarvis."""
    if palabra in suyas:
        return True
    if len(palabra) < 5:
        return False
    # Whisper también junta palabras: "mal oída" -> "maloída" (02-oct)
    if pegado and palabra in pegado:
        return True
    return any(len(w) >= 5 and SequenceMatcher(None, palabra, w).ratio() >= 0.8
               for w in suyas)


def es_corte(oido, dicho=""):
    """Orden de corte. Si Jarvis también dijo esa palabra ("sirve PARA probar"), el
    eco la traería: entonces solo cuenta si se oyó la orden sola ("¡para!")."""
    encontradas = CORTE.findall(normalizar(oido))
    if not encontradas:
        return False
    if len(oido.split()) > 8:
        return False  # una frase larga con "para" dentro no es una orden de corte
    dicho_n = f" {normalizar(dicho)} "
    if any(f" {w} " not in dicho_n for w in encontradas):
        return True
    return solo_corte(oido)


def solo_corte(oido):
    """True si no hay nada más que la orden de corte (no hace falta pegarla)."""
    resto = CORTE.sub(" ", normalizar(oido))
    return not [w for w in resto.split() if w not in COMUNES]


def es_eco(oido, dicho):
    """True si `oido` parece el micro oyendo a Jarvis decir `dicho`.

    `dicho` vacío o desconocido (marcas antiguas que solo escriben "1"): no hay con
    qué comparar y se trata como eco, que era el comportamiento anterior.
    """
    if es_corte(oido, dicho):
        return False
    palabras = normalizar(oido).split()
    if not palabras:
        return True
    # lo que Whisper se inventa con ruido o voz confusa ("¡Gracias!"): con Jarvis
    # hablando, casi seguro que es su eco mal oído
    if " ".join(palabras) in INVENTOS:
        return True
    dicho_n = normalizar(dicho)
    if not dicho_n or dicho_n == "1":
        return True
    lista = dicho_n.split()
    suyas = set(lista)
    pegado = "".join(lista)
    # Frases seguidas: si la mitad de las parejas de palabras oídas aparecen tal cual en
    # lo que dijo Jarvis, es su eco aunque Whisper destroce la última palabra
    # ("en vez de distinguir" oído como "en vez de distraerlo", 02-oct).
    pares = list(zip(palabras, palabras[1:]))
    if pares and sum(par in set(zip(lista, lista[1:])) for par in pares) / len(pares) >= 0.5:
        return True
    distintivas = [w for w in palabras if w not in COMUNES]
    # Nada distintivo: no hay pruebas. Se exige que TODO coincida antes de tirarlo,
    # perder una pregunta real cuesta más que dejar pasar un eco suelto.
    # Trozo corto hecho solo de palabras comunes ("Con todo." era "Voy con ello."
    # mal oído, 02-oct): con Jarvis hablando no aporta nada y casi siempre es su eco.
    # Las órdenes de corte ya se miraron arriba, así que "para" o "calla" sí pasan.
    # Igual con cualquier trozo de 1-2 palabras: "de vida" era "mal oída" (02-oct).
    # Para cortar a Jarvis basta una orden ("para") o una frase de 3+ palabras.
    if len(palabras) <= 2 or (not distintivas and len(palabras) <= 3):
        return True
    if len(distintivas) < 2:
        # (una sola palabra suelta que Jarvis también dijo: trozo de eco, fuera)
        return all(_parecida(w, suyas, pegado) for w in palabras)
    aciertos = sum(_parecida(w, suyas, pegado) for w in distintivas)
    return aciertos / len(distintivas) >= 0.6


def restar(oido, sonado):
    """Quita de lo oído por el micro lo que estaba sonando por los altavoces (vídeo,
    música...): `sonado` es la transcripción de la captura 'loopback' del mismo rato.

    03-oct 18:55: la huella de voz no separa al usuario de un vídeo que suena A LA VEZ
    (el usuario mezclado 0,13-0,34, vídeo solo 0,01-0,37). El texto sí: lo que dice el vídeo
    sale en las dos transcripciones y lo del usuario solo en la del micro. Se quitan los
    tramos seguidos con 2 o más palabras no comunes que también suenan por los
    altavoces; una palabra suelta coincidente se queda (el usuario puede decirla también).
    Devuelve el texto que queda ("" si no queda nada del usuario)."""
    suyas = set(normalizar(sonado).split())
    if not suyas:
        return oido
    pegado = normalizar(sonado).replace(" ", "")
    toks = oido.split()
    norm = [normalizar(t) for t in toks]
    # 1 = suena por los altavoces, 0 = no, None = común (ni suma ni corta un tramo)
    marca = [None if (not n or all(w in COMUNES for w in n.split()))
             else int(all(_parecida(w, suyas, pegado) for w in n.split())) for n in norm]
    quitar = [False] * len(toks)
    i = 0
    while i < len(toks):
        if marca[i] != 1:
            i += 1
            continue
        j, fuertes = i, 0
        while j < len(toks) and marca[j] != 0:
            fuertes += marca[j] == 1
            j += 1
        if fuertes >= 2:
            for k in range(i, j):
                quitar[k] = True
        i = j
    resto = [t for t, q in zip(toks, quitar) if not q]
    if not any(m == 1 or m == 0 for m, q in zip(marca, quitar) if not q and m is not None):
        return ""
    if not [w for t in resto for w in normalizar(t).split() if w not in COMUNES]:
        return ""
    return " ".join(resto).strip()
