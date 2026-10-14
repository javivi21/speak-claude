# Dictado por voz continuo

Micrófono siempre escuchando. Hablas, el texto aparece en la ventana donde tengas el cursor,
y si te callas 5 segundos se envía solo (Enter). Sin tocar el ratón.

## Uso por voz (recomendado)

Dile a Claude Code:

- **"activa modo escucha"** → arranca el dictado en segundo plano (`activar.ps1`)
- **"para modo escucha"** → lo detiene (`parar.ps1`)

La primera activación hay que escribirla: con el micrófono apagado nadie puede oírte.
A partir de ahí, "para modo escucha" ya funciona dictado.

## Uso manual

1. Doble clic en `dictado.cmd`.
2. Espera a `ESCUCHANDO` (el modelo tarda ~35 s en cargar la primera vez).
3. **Haz clic en la ventana donde quieras dictar** (la caja del prompt de Claude Code).
4. Habla. Al callar 1 s se transcribe y aparece el texto; al llegar a 5 s se envía.

| Tecla | Acción |
|-------|--------|
| `F9`  | Pausar / reanudar la escucha |
| `F10` | Salir |

Si vuelves a hablar antes de los 5 s, la frase nueva se añade detrás y el contador se reinicia.

## Ajustes (`config.json`)

| Clave | Qué hace |
|-------|----------|
| `segundos_para_enviar` | Silencio necesario para pulsar Enter. |
| `segundos_para_transcribir` | Silencio que cierra una frase y la escribe en pantalla. |
| `sensibilidad` | Cuánto debe superar tu voz al ruido de fondo. Súbelo si capta ruido, bájalo si no te oye. |
| `enviar_automatico` | `false` para que escriba pero nunca pulse Enter. |
| `microfono` | `null` usa el predeterminado de Windows. Para elegir otro: `dictado.cmd --listar-micros`. |
| `modelo` | `large-v3` es el más preciso. `medium` o `small` cargan antes y gastan menos VRAM. |

## Notas

- Escribe en la ventana que esté activa en ese momento: si cambias de ventana, escribirá allí.
- Todo se procesa en local, en la GPU. No sale audio del ordenador.
