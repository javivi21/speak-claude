"""Diccionario de pronunciación: cómo se dicen en voz alta las palabras que Piper
lee mal con reglas del español (medido con los fonemas de Piper el 21-sep-2026).

Cada entrada es 'palabra escrita' -> 'cómo se escribe para que suene bien'. Solo se
toca la palabra entera (con plural en -s), sin distinguir mayúsculas.
"""
import re

# Fallos claros medidos: skills -> "eskiys" (ll española), Ollama -> "olyama",
# hook -> "oók", GitHub -> "jit-ub", API/CLI como si fueran palabras.
DICCIONARIO = {
    "skill": "eskil",
    "hook": "juk",
    "github": "guitjab",
    "commit": "comit",
    "api": "a pe i",
    "cli": "ce ele i",
    "piper": "páiper",
    "whisper": "guísper",
    "python": "páiton",
    "json": "yéison",
    # Claude como "clod" y Sonnet sin la n doble que Piper alarga; Opus, Jarvis y Max se dicen tal cual
    "claude": "clod",
    "sonnet": "sonet",
    # medidos el 24-sep-2026 con los fonemas de Piper: URL/USB salían "url"/"usb" de
    # una sílaba, online con acento en la i, Telegram con acento en la e, ok como "ok"
    "url": "u erre ele",
    "usb": "u ese be",
    "online": "onlain",
    "offline": "oflain",
    "telegram": "telegrám",
    "ok": "oquei",
    "email": "imeil",
    "gb": "gigas",
    "mb": "megas",
}
# Sin tocar, tal como Piper los lee: añade aquí los nombres propios que quieras conservar.

MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre")

# Frases y números romanos (patrón, sustitución), antes que el diccionario.
# Frases y números romanos (patrón, sustitución), antes que el diccionario.
FRASES = [
    # fechas 24-09-2026 o 24/09/2026: Piper decía "veinticuatro cero nueve dos mil..."
    (re.compile(r"\b([0-3]?\d)[-/](0?[1-9]|1[0-2])[-/]((?:19|20)\d\d)\b"),
     lambda m: f"{int(m.group(1))} de {MESES[int(m.group(2)) - 1]} de {m.group(3)}"),
    (re.compile(r"\bvs\.?(?=\s)", re.IGNORECASE), "contra"),
]

_PATRON = re.compile(r"\b(" + "|".join(sorted(DICCIONARIO, key=len, reverse=True)) + r")(s?)\b",
                     re.IGNORECASE)


def normalizar(texto):
    """Solo las FRASES (fechas, vs): valen para cualquier
    voz. ElevenLabs usa esto; el DICCIONARIO fonético es solo para Piper."""
    for patron, bien in FRASES:
        texto = patron.sub(bien, texto)
    return texto


def pronunciable(texto):
    texto = normalizar(texto)
    return _PATRON.sub(lambda m: DICCIONARIO[m.group(1).lower()] + m.group(2), texto)


# --- Números en palabras (solo ElevenLabs, 14-oct-2026) -------------------------------
# el usuario: "cuando dices números se te lía la boca". ElevenLabs lee mal las cifras sueltas
# (teléfonos, pólizas, DNI, importes). Aquí se pasan a palabras antes de enviar el texto.
# Piper NO pasa por aquí: lee bien las cifras y sus pruebas esperan los dígitos.
_U = ["cero", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez",
      "once", "doce", "trece", "catorce", "quince", "dieciséis", "diecisiete", "dieciocho",
      "diecinueve", "veinte", "veintiuno", "veintidós", "veintitrés", "veinticuatro",
      "veinticinco", "veintiséis", "veintisiete", "veintiocho", "veintinueve"]
_D = ["", "", "", "treinta", "cuarenta", "cincuenta", "sesenta", "setenta", "ochenta", "noventa"]
_C = ["", "ciento", "doscientos", "trescientos", "cuatrocientos", "quinientos", "seiscientos",
      "setecientos", "ochocientos", "novecientos"]
_LETRAS = {"A": "a", "B": "be", "C": "ce", "D": "de", "E": "e", "F": "efe", "G": "ge",
           "H": "hache", "I": "i", "J": "jota", "K": "ka", "L": "ele", "M": "eme", "N": "ene",
           "Ñ": "eñe", "O": "o", "P": "pe", "Q": "cu", "R": "erre", "S": "ese", "T": "te",
           "U": "u", "V": "uve", "W": "uve doble", "X": "equis", "Y": "ye", "Z": "zeta"}


def _menor_cien(n):
    if n < 30:
        return _U[n]
    d, u = divmod(n, 10)
    return _D[d] + ("" if u == 0 else " y " + _U[u])


def _menor_mil(n):
    if n == 100:
        return "cien"
    c, r = divmod(n, 100)
    return " ".join(x for x in (_C[c], _menor_cien(r) if r else "") if x)


def _apocope(txt):
    if txt.endswith("veintiuno"):
        return txt[:-9] + "veintiún"
    return txt[:-1] if txt.endswith("uno") else txt


def letras(n):
    """Entero (0 a 999 999 999) en palabras: 1234 -> 'mil doscientos treinta y cuatro'."""
    if n == 0:
        return "cero"
    millones, resto = divmod(n, 1_000_000)
    miles, cientos = divmod(resto, 1000)
    partes = []
    if millones:
        partes.append("un millón" if millones == 1 else letras(millones) + " millones")
    if miles:
        partes.append("mil" if miles == 1 else _apocope(_menor_mil(miles)) + " mil")
    if cientos:
        partes.append(_menor_mil(cientos))
    return " ".join(partes)


def _digitos(cifras, grupo=3):
    """'919154154' -> 'nueve uno nueve, uno cinco cuatro, uno cinco cuatro' (con pausas)."""
    palabras = [_U[int(c)] for c in cifras]
    trozos = [" ".join(palabras[i:i + grupo]) for i in range(0, len(palabras), grupo)]
    return ", ".join(trozos)


_MASCULINAS_EN_A = r"(?!(?:d[ií]as?|problemas?|programas?|sistemas?|temas?|mapas?|idiomas?|climas?)\b)"
_FEMENINA = re.compile(r"\s+" + _MASCULINAS_EN_A + r"(?:\w*(?:a|as|ión|iones|ad|ades)|vez|veces)\b",
                       re.IGNORECASE)


def _entero(txt, siguiente=""):
    n = int(txt)
    if n > 999_999_999:
        return _digitos(txt)
    pal = letras(n)
    if pal.endswith("uno"):
        if _FEMENINA.match(siguiente or ""):
            pal = pal[:-3] + "una"
        else:
            pal = _apocope(pal)
    return pal


def _importe(m):
    ent, dec = m.group(1).replace(".", ""), m.group(2)
    n = int(ent)
    txt = ("un euro" if n == 1 else _apocope(letras(n)) + " euros") if n else "cero euros"
    if dec and int(dec):
        c = int(dec.ljust(2, "0"))
        txt += " con " + ("un céntimo" if c == 1 else letras(c) + " céntimos")
    return txt


def numeros_a_letras(texto):
    """Cifras a palabras: teléfonos, DNI, pólizas dígito a dígito; importes, porcentajes,
    decimales y enteros como cantidad. Se aplica después de normalizar (fechas)."""
    t = texto
    # DNI/NIE: 7-8 cifras + letra -> dígitos y nombre de la letra
    t = re.sub(r"\b(\d{7,8})([A-Za-zÑñ])\b",
               lambda m: _digitos(m.group(1)) + ", " + _LETRAS.get(m.group(2).upper(), m.group(2)), t)
    # teléfonos de 9 cifras (6-9 al inicio), pegados o con espacios, puntos o guiones
    t = re.sub(r"(?<![\d.,])([6-9]\d{2})[ .-]?(\d{3})[ .-]?(\d{3})(?!\d)(?![.,]\d)(?!\s?€)",
               lambda m: _digitos(m.group(1) + m.group(2) + m.group(3)), t)
    # cualquier otra cifra larga (pólizas, referencias): dígito a dígito
    t = re.sub(r"(?<![\w.,])\d{7,}(?!\w)(?![.,]\d)", lambda m: _digitos(m.group(0)), t)
    # importes: 838,54 € / 1.200 euros
    t = re.sub(r"(?<![\w.,])(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d{1,2}))?\s?(?:€|euros?\b)", _importe, t)
    # porcentajes
    t = re.sub(r"(?<![\w.,])(\d+)(?:,(\d+))?\s?%",
               lambda m: _entero(m.group(1)) + (" coma " + _entero(m.group(2)) if m.group(2) else "")
               + " por ciento", t)
    # decimales: 3,5 -> tres coma cinco
    t = re.sub(r"(?<![\w.,])(\d+),(\d+)(?![\w]|,\d)",
               lambda m: _entero(m.group(1)) + " coma "
               + (_entero(m.group(2)) if len(m.group(2)) <= 2 and m.group(2)[0] != "0"
                  else _digitos(m.group(2), 1).replace(", ", " ")), t)
    # miles con punto: 1.234 -> mil doscientos treinta y cuatro
    t = re.sub(r"(?<![\w.,])\d{1,3}(?:\.\d{3})+(?!\w)(?![.,]\d)",
               lambda m: letras(int(m.group(0).replace(".", ""))), t)
    # enteros sueltos
    t = re.sub(r"(?<![\w.,])(\d+)(?!\w)",
               lambda m: _entero(m.group(1), t[m.end():m.end() + 25]), t)
    return t


def para_eleven(texto):
    """Lo que se manda a ElevenLabs: frases (fechas...) y luego números en palabras."""
    return numeros_a_letras(normalizar(texto))


PAUSA_FRASES = 0.22  # segundos de silencio entre frases (a velocidad 1.0)


ABREVIATURAS = ("sr", "sra", "dr", "dra", "vs", "etc", "ej", "pág", "núm", "aprox", "p")

# Expresividad por frase según cómo termina. Las afirmaciones quedan estables (lo que
# el usuario eligió, 21-sep). MEDIDO ese día: noise_scale NO mueve el tono (0,3 -> 1,2 da 2,43
# -> 2,54 semitonos, dentro del ruido de +-0,24), así que se usan palancas que sí
# responden: ritmo, tono de la frase (vocoder de fase) y energía.
#   "?": el tono sube en el último tramo (entonación de pregunta).
#   "!": frase algo más aguda, más rápida y con más energía.
EXPRESIVIDAD = {
    "?": {"ritmo": 1.03, "subida": 2.0, "tono": 0.0, "ganancia": 1.0},
    "!": {"ritmo": 0.95, "subida": 0.0, "tono": 1.0, "ganancia": 1.15},
}


def dividir_frases(texto):
    """Parte en frases por . ! ? … sin romper abreviaturas ("Sr. López", "etc. Luego")."""
    partes = re.split(r"(?<=[.!?…])\s+(?=[A-ZÁÉÍÓÚÑ¡¿0-9])", texto.strip())
    frases = []
    for p in partes:
        if frases and re.search(r"\b(?:" + "|".join(ABREVIATURAS) + r")\.$", frases[-1], re.IGNORECASE):
            frases[-1] += " " + p
        elif p:
            frases.append(p)
    return frases


def _tipo_frase(frase):
    fin = frase.rstrip(" \"')»”").rstrip()[-1:] if frase.strip() else ""
    return fin if fin in EXPRESIVIDAD else ""


# Preguntas parciales (¿qué...?, ¿cómo...?): en español NO suben al final, arrancan
# altas y caen. Solo las de sí/no suben. Antes todas subían (sonaba a pregunta de robot).
_PARCIAL = re.compile(r"^\W*(?:y\s+|pero\s+|entonces\s+)?(?:qu[eé]|c[oó]mo|d[oó]nde|ad[oó]nde|cu[aá]ndo|"
                      r"qui[eé]n(?:es)?|cu[aá]l(?:es)?|cu[aá]nt[oa]s?|por\s*qu[eé]|para\s+qu[eé])\b",
                      re.IGNORECASE)


def pregunta_parcial(frase):
    """¿Es una pregunta con partícula interrogativa? Mira desde el último ¿."""
    trozo = frase[frase.rfind("¿"):] if "¿" in frase else frase
    return _tipo_frase(frase) == "?" and bool(_PARCIAL.match(trozo))


def _pulir(audio, sr, umbral=0.02):
    """Arranque y final suaves y silencios de Piper recortados.

    MEDIDO (24-sep): Piper deja 10-95 ms de silencio variable delante y detrás de cada
    frase (pausas irregulares) y algunas frases arrancan de golpe (0,8 de amplitud en
    10 ms: el "arranque artificial"). Se deja un margen fijo y un fundido coseno que
    nunca llega a cero exacto (no inventa silencio)."""
    import numpy as np

    voz = np.flatnonzero(np.abs(audio) > umbral)
    if not len(voz):
        return audio
    margen = int(sr * 0.015)
    a = audio[max(0, voz[0] - margen):voz[-1] + margen].astype("float32", copy=True)
    for n, final in ((int(sr * 0.05), False), (int(sr * 0.04), True)):
        n = min(n, len(a) // 4)
        if n > 1:
            r = (0.5 - 0.5 * np.cos(np.linspace(0, np.pi, n + 1)[1:])).astype("float32")
            if final:
                a[-n:] *= r[::-1]
            else:  # entrada algo más lenta al principio: una vocal inicial ya no golpea
                a[:n] *= r ** 1.5
    return a


def _igualar(audio, objetivo=0.16, techo=0.95):
    """Mismo volumen percibido en todas las frases (RMS de la parte con voz).

    Piper normaliza cada frase por su PICO (0,99 medido): unas suenan más fuertes que
    otras y rozan la saturación."""
    import numpy as np

    voz = audio[np.abs(audio) > 0.02]
    if len(voz) < 100:
        return audio
    g = objetivo / (float(np.sqrt(np.mean(voz ** 2))) + 1e-9)
    g = min(g, techo / (float(np.max(np.abs(audio))) + 1e-9))
    return (audio * g).astype("float32")


# Pausa tras cada tipo de frase, relativa a 'pausa': una pregunta pide un respiro más
PAUSA_TIPO = {"": 1.0, "?": 1.3, "!": 1.1}


def _configuracion(e, velocidad, frase):
    from piper import SynthesisConfig

    fuerza = e.get("expresividad", 1.0)  # 0 apaga la expresividad por frase
    mod = EXPRESIVIDAD.get(_tipo_frase(frase))
    ritmo = e.get("length_scale", 1.0)
    if mod and fuerza:
        ritmo *= 1 + (mod["ritmo"] - 1) * fuerza
    ritmo /= velocidad  # length_scale alarga la voz: es el inverso de la velocidad
    return SynthesisConfig(length_scale=ritmo if ritmo != 1.0 else None,
                           noise_scale=e.get("noise_scale"), noise_w_scale=e.get("noise_w_scale"),
                           volume=e.get("volume", 1.0), speaker_id=e.get("speaker_id"))


def _dar_vida(trozos, tipo, fuerza, parcial=False):
    """Modela el tono/energía de los trozos de UNA frase según su tipo (?, !)."""
    import efectos
    import numpy as np

    mod = EXPRESIVIDAD.get(tipo)
    if not mod or not fuerza:
        return trozos
    salida = []
    for i, (audio, sr) in enumerate(trozos):
        if mod["tono"]:
            audio = efectos.cambiar_tono(audio, sr, mod["tono"] * fuerza)
        if mod["ganancia"] != 1.0:
            audio = np.clip(audio * (1 + (mod["ganancia"] - 1) * fuerza), -1.0, 1.0).astype("float32")
        if mod["subida"] and i == len(trozos) - 1 and not parcial:  # solo el último trozo de la pregunta
            audio = efectos.subida_final(audio, sr, mod["subida"] * fuerza)
        salida.append((audio, sr))
    return salida


def _limites_clausula(audio, sr, fonemas):
    """Instantes (s) donde acaban las cláusulas internas (coma, ; :) dentro de una frase.

    Piper no da duraciones por fonema: se estima la posición por la proporción de
    fonemas y se ajusta al hueco de energía más cercano (Piper deja una pausita ahí)."""
    import numpy as np

    fon = [f for f in fonemas]
    letras = [i for i, f in enumerate(fon) if f.isalpha()]
    if len(letras) < 6:
        return []
    ventana = max(1, int(sr * 0.01))
    energia = np.array([np.sqrt(np.mean(audio[i:i + ventana] ** 2))
                        for i in range(0, len(audio) - ventana, ventana)])
    puntos = []
    for i, f in enumerate(fon[:-1]):  # el último signo (fin de frase) no cuenta
        if f in (",", ";", ":") and any(g.isalpha() for g in fon[i + 1:]):
            antes = sum(1 for j in letras if j < i)
            t = antes / len(letras) * len(audio) / sr
            a, b = int(max(0, t - 0.15) * 100), int(min(len(audio) / sr - 0.1, t + 0.15) * 100)
            if b > a:
                t = (a + int(np.argmin(energia[a:b]))) / 100
            if 0.25 < t < len(audio) / sr - 0.25:
                puntos.append(t)
    return puntos


def _melodia_frase(audio, sr, frase, fonemas, fuerza, expresividad=1.0):
    """Curva de tono y energía de una frase: acento al arrancar, caída al terminar,
    continuación en las comas, subida final en preguntas, y una variación pequeña
    distinta en cada frase para que no suenen todas con la misma melodía."""
    import numpy as np
    import efectos

    dur = len(audio) / sr
    cortes = _limites_clausula(audio, sr, fonemas)
    inicios = [0.0] + cortes
    fines = cortes + [dur]
    tipo = _tipo_frase(frase)
    parcial = pregunta_parcial(frase)
    import zlib
    azar = np.random.default_rng(zlib.crc32(frase.encode("utf-8")))  # repetible por frase
    a0, d0 = azar.uniform(-0.5, 0.5), azar.uniform(-0.3, 0.3)  # variación de esta frase

    def clausula(t):
        i = max(0, int(np.searchsorted(inicios, t, side="right")) - 1)
        return min(i, len(inicios) - 1)

    def st(t):
        t = np.asarray(t, dtype="float64")
        y = np.zeros_like(t)
        for i, (ini, fin) in enumerate(zip(inicios, fines)):
            m = (t >= ini) & (t < fin) if i < len(inicios) - 1 else (t >= ini)
            u, largo = t[m] - ini, max(fin - ini, 0.2)
            acento = (0.9 + a0 if i == 0 else 0.9) * np.exp(-u / 0.28)
            ultima = i == len(inicios) - 1
            fin_st = (-1.0 + d0) if ultima and (tipo == "" or parcial) else (0.4 if not ultima else 0.0)
            deriva = fin_st * np.clip((u - 0.15) / max(largo - 0.15, 0.1), 0, 1)
            y[m] = (acento + deriva) * fuerza
            # la pregunta NO depende de 'melodia': con melodía 0,3 (voz M) la subida era
            # de 0,66 semitonos, casi imperceptible. Va con la expresividad.
            if ultima and tipo == "?" and not parcial:
                y[m] += 4.5 * expresividad * np.clip((u - (largo - 0.5)) / 0.5, 0, 1) ** 1.3
            if tipo == "?" and parcial and i == 0:  # parcial: arranca alta
                y[m] += 1.2 * expresividad * np.exp(-u / 0.35)
            if tipo == "!":  # exclamación: toda la frase algo más aguda (como sin melodía)
                y[m] += 1.0 * expresividad
            if ultima and tipo == "!":
                y[m] += fuerza * (0.6 * np.clip(1 - u / largo, 0, 1)
                                  - 0.5 * np.clip((u - largo * 0.6) / (largo * 0.4), 0, 1))
        return y

    def db(t):
        t = np.asarray(t, dtype="float64")
        return fuerza * (1.2 * np.exp(-t / 0.25) - 2.5 * np.clip((t - dur * 0.7) / (dur * 0.3), 0, 1))

    return efectos.melodia(audio, sr, st, db)


def frases_piper(voz, texto, velocidad=1.0, estilo=None):
    """Genera (audio float32, sample_rate) trozo a trozo, en cuanto cada uno está listo.

    Permite empezar a hablar tras la primera frase (0,13 s de media en vez de esperar
    a todo el texto, 0,42 s). Cada frase se sintetiza con su propia expresividad y
    lleva delante una pausa corta salvo la primera. Diccionario aplicado."""
    import numpy as np

    e = estilo or {}
    pausa = e.get("pausa", PAUSA_FRASES)
    primero, resto, sr, pausa_antes = True, np.zeros(0, "float32"), 22050, pausa
    for frase in dividir_frases(pronunciable(texto)):
        piezas = list(voz.synthesize(frase, syn_config=_configuracion(e, velocidad, frase)))
        melodia = e.get("melodia", 0.0)
        # volumen igualado y bordes pulidos ANTES de la melodía (que añade sus acentos)
        crudo = [(_pulir(_igualar(c.audio_float_array), c.sample_rate), c.sample_rate, c)
                 for c in piezas]
        if melodia:  # curva propia de tono/energía: sustituye a los retoques sueltos de ?/!
            vida = [(_melodia_frase(a, s, frase, c.phonemes, melodia, e.get("expresividad", 1.0)), s)
                    for a, s, c in crudo]
        else:
            vida = _dar_vida([(a, s) for a, s, _ in crudo], _tipo_frase(frase),
                             e.get("expresividad", 1.0), pregunta_parcial(frase))
        for audio, sr in vida:
            cola = np.zeros(0, "float32")
            if e.get("efectos"):  # carácter propio de la voz (tono, pixel, metal, reverb)
                import efectos
                largo = len(audio)
                audio = efectos.aplicar(audio, sr, e["efectos"])
                # la reverberación alarga el audio: su cola no debe sumarse a cada trozo
                # (alargaba cada pausa 0,2 s), se mezcla con el silencio del siguiente
                audio, cola = audio[:largo], audio[largo:]
            if not primero:
                audio = np.concatenate([np.zeros(int(sr * pausa_antes / velocidad), "float32"), audio])
            if len(resto):
                if len(resto) > len(audio):
                    audio = np.concatenate([audio, np.zeros(len(resto) - len(audio), "float32")])
                audio[:len(resto)] += resto
            primero, resto, pausa_antes = False, cola, pausa
            yield audio, sr
        pausa_antes = pausa * PAUSA_TIPO.get(_tipo_frase(frase), 1.0)
    if len(resto):  # la cola del último trozo suena al final
        yield resto, sr


def sintetizar_piper(voz, texto, velocidad=1.0, estilo=None):
    """Todo el audio de golpe (CLI, pruebas, cata): (audio float32, sample_rate).

    `estilo` (dict opcional) afina la voz: pausa, ritmo (length_scale), variación
    (noise_scale, noise_w_scale), expresividad (0-1), volume, speaker_id y 'efectos'
    (receta de efectos.py). Sin él, valores por defecto."""
    import numpy as np

    trozos, sr = [], None
    for audio, sr in frases_piper(voz, texto, velocidad, estilo):
        trozos.append(audio)
    if not trozos:
        raise ValueError("Piper no devolvió audio")
    return np.concatenate(trozos), sr
