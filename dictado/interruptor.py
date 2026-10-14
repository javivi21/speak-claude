"""Interrumpir a la voz de Claude hablando por encima (nivel 12 de la voz de Claude).

Sin auriculares el micro oye a Jarvis, y Silero lo detecta como voz (lo es).
Lo que distingue al usuario es el VOLUMEN: su voz llega al micro mucho más fuerte
que el eco de los altavoces. Mientras Jarvis habla se aprende el nivel del eco
(percentil alto de los últimos segundos) y solo se interrumpe si hay voz clara,
bastante más fuerte que ese eco, durante un rato seguido.

Solo usa numpy: se prueba desde el banco de la voz de Claude sin cargar Whisper.
"""
from collections import deque

import numpy as np

AJUSTES = {
    # MÓDULO AURICULARES: apagado por defecto. Con altavoces falló en vivo (21-sep:
    # Jarvis se cortaba solo con su eco). Encender solo con auriculares puestos.
    "interrumpir_hablando": False,
    "interrumpir_probabilidad": 0.7,  # Silero: voz clara
    # veces más fuerte que el eco. Con auriculares el eco es casi nulo: margen amplio
    "interrumpir_factor": 3.0,
    "interrumpir_rms_minimo": 0.02,  # por debajo es ruido, nunca interrumpe
    # 5 bloques fuertes (~0,16 s) dentro de una ventana de 16 (~0,5 s): la voz
    # tiene huecos entre sílabas ("para, para") y exigirlos seguidos no dispara nunca
    "interrumpir_bloques": 5,
    "interrumpir_ventana": 16,
    # ~0,8 s de VOZ de Jarvis aprendiendo el eco antes de decidir. Con 0,5 s de
    # bloques cualesquiera aprendía el silencio inicial de Piper y se cortaba solo
    # (prueba en vivo 21-sep: "está el dicta", voz 0,036 > eco 0,016)
    "interrumpir_calentamiento": 24,
}


def rms(bloque):
    return float(np.sqrt(np.mean(np.square(bloque, dtype="float64")))) if len(bloque) else 0.0


class Interruptor:
    def __init__(self, cfg=None):
        self.cfg = {**AJUSTES, **(cfg or {})}
        self.reiniciar()

    def reiniciar(self):
        """Al empezar cada lectura de Jarvis: el eco depende del volumen de cada vez."""
        self.eco = deque(maxlen=94)  # ~3 s de historia
        self.vistos = 0
        self.votos = deque(maxlen=self.cfg["interrumpir_ventana"])
        self.racha = []  # audio desde el primer candidato (se devuelve al interrumpir)
        self.ultimo = (0.0, 0.0)  # (rms, eco) del último disparo, para el log

    def nivel_eco(self):
        return float(np.percentile(self.eco, 90)) if self.eco else 0.0

    def __call__(self, bloque, probabilidad):
        """Devuelve la lista de bloques de voz si hay que interrumpir; si no, None."""
        c = self.cfg
        if not c["interrumpir_hablando"]:
            return None
        nivel = rms(bloque)
        self.vistos += 1  # se cuenta por bloques vistos, no por eco aprendido: con
        # auriculares no hay eco y el calentamiento no acabaría nunca
        calentando = self.vistos < c["interrumpir_calentamiento"]
        eco = self.nivel_eco()
        candidato = (
            not calentando
            and probabilidad > c["interrumpir_probabilidad"]
            and nivel > max(c["interrumpir_rms_minimo"], c["interrumpir_factor"] * eco)
        )
        self.votos.append(candidato)
        if not any(self.votos):
            # sin candidatos recientes: es eco puro y se aprende, pero solo si hay
            # voz (los silencios entre frases bajarían el umbral). Cerca de un
            # candidato NO: la voz del usuario subiría el umbral y no se le oiría
            if probabilidad > 0.5:
                self.eco.append(nivel)
            self.racha = []
            return None
        self.racha.append(bloque)
        if sum(self.votos) >= c["interrumpir_bloques"]:
            voz, self.racha = self.racha, []
            self.votos.clear()
            self.ultimo = (nivel, eco)
            return voz
        return None
