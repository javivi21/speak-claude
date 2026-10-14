"""Casos reales del filtro de eco (eco.py). Ejecutar: .venv\\Scripts\\python.exe prueba_eco.py

Cada caso: (lo que dijo Jarvis, lo que oyó el micro, ¿es eco?). Añadir aquí cada fuga
o corte en falso que aparezca en dictado.log.
"""
import eco

D1 = "Ya está. A partir de ahora te hablo con la voz de Daniel, y si falla internet vuelvo a la de siempre."
D2 = "Esto sirve para probar la voz, espera un segundo que termino."
D3 = ("Lo especial de ese programa es una idea sencilla: en vez de distinguir mi voz de la "
      "tuya por el volumen, como hacíamos nosotros, compara las palabras que oye con las que está diciendo.")
D4 = ("Sí, era mi propia frase de espera mal oída. Me estaba acoplando: dos de tus frases eran en realidad mi propia voz mal oída. "
      "Ahora el filtro reconoce también palabras parecidas.")

CASOS = [
    (D1, "a partir de ahora te hablo con la voz de daniel", True),
    (D1, "si falla internet vuelvo a la de siempre", True),
    (D1, "Daniel", True),
    (D1, "la voz", True),
    (D1, "falla internet", True),
    (D1, "Espera, espera", False),
    (D1, "para", False),
    (D1, "¿Y cuánto cuesta eso al mes?", False),
    (D1, "Oye, apúntame lo del gimnasio para mañana", False),
    (D1, "vale", True),  # palabra común suelta mientras Jarvis habla: se trata como eco
    (D1, "quiero cambiar la voz por otra más grave", False),
    (D2, "sirve para probar la voz", True),
    (D2, "espera un segundo que termino", True),
    (D2, "para", False),
    (D2, "¡Para, para!", False),
    (D2, "espera", False),
    (D2, "calla", False),
    (D2, "para que quiero otra cosa", False),
    (D3, "En vez de distraerlo.", True),  # 02-oct: se coló y Jarvis se cortó solo
    (D3, "distinguirme.", True),  # 02-oct: ídem
    (D3, "compara las palabras", True),
    (D3, "por el volumen", True),
    (D3, "te estás acoplando tú mismo", False),
    (D3, "no, espera, eso no es lo que te he pedido", False),
    (D3, "la voz de Daniel me gusta más", False),
    (D4, "voz maloída.", True),  # 02-oct: Whisper juntó "mal oída"
    (D4, "quiero otra cosa distinta", False),
    ("Voy con ello.", "Con todo.", True),
    (D4, "de vida.", True),  # 02-oct: "mal oída" mal oído  # 02-oct: frase de espera mal oída
    ("Estoy en ello.", "Estoy en ello.", True),
    ("Frase numero 9 del estres.", "¡Gracias!", True),  # invento típico de Whisper
    ("1", "cualquier cosa", True),  # marca antigua sin texto: todo es eco
]

if __name__ == "__main__":
    fallos = [(o, e) for d, o, e in CASOS if eco.es_eco(o, d) != e]
    for o, e in fallos:
        print(f"FALLO: {o!r} debería ser {'eco' if e else 'el usuario'}")
    print(f"{len(CASOS) - len(fallos)}/{len(CASOS)} casos bien")
