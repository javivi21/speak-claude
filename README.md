# speak-claude

Habla con Claude Code y que Claude te conteste hablando. Para Windows, con la voz y el dictado funcionando en tu propio ordenador.

- **Claude habla (`voz/`)**: al terminar cada respuesta, Claude lee en voz alta un resumen corto. Usa Piper (gratis, sin internet) o, si quieres una voz más natural, ElevenLabs.
- **Tú hablas (`dictado/`)**: el micrófono escucha, lo que dices aparece en la ventana de Claude y se envía solo tras un silencio. Usa Whisper en tu GPU o en la CPU.

Los dos trabajan juntos: el dictado sabe cuándo habla Claude para no confundir su voz con la tuya.

> Proyecto independiente, no oficial. "Claude" es una marca de Anthropic.

## Instalar (casi todo es pulsar Enter)
1. Descarga el repo (botón verde **Code > Download ZIP**) y descomprímelo.
2. Haz doble clic en **`instalar.cmd`**.

El instalador hace solo lo siguiente:
- Instala Python 3.12 si no lo tienes.
- Instala la voz y el dictado y descarga los modelos (unos 300 MB).
- Detecta si tienes tarjeta NVIDIA; si no, configura el dictado para CPU.
- Te pregunta si quieres **ElevenLabs** (por defecto no). Si dices que sí, abre la página de claves; tú creas la clave y la pegas, y el asistente te deja **escuchar varias voces** para que elijas con un número.
- Conecta Claude Code (añade el aviso de voz y el arranque automático, con copia de seguridad de tus archivos).
- Arranca la voz.

Después abre Claude Code y escribe cualquier cosa.

## Manejo diario
| Quiero | Hago |
|---|---|
| Pausar o reanudar el dictado | F9 |
| Cerrar el dictado | F10 dos veces seguidas |
| Silenciar a Claude sin apagarlo | Crear el archivo `voz\SILENCIO` (bórralo para reactivar) |
| Que Claude lea una respuesta entera | Pídeselo: "léemelo tal cual" |
| Cambiar de voz de ElevenLabs | `voz\.venv\Scripts\python.exe voz\configurar_eleven.py` (con tu clave en la variable `ELEVENLABS_API_KEY`) |
| Parar todo | `voz\parar.ps1` y `dictado\parar.ps1` |

## ElevenLabs en dos minutos
1. El instalador abre https://elevenlabs.io/app/settings/api-keys.
2. Entra o crea tu cuenta gratis. Pulsa **Create API Key** y luego **Create**.
3. Copia la clave y pégala en el instalador (no se ve al pegarla).
4. Escucha las voces que van sonando y elige un número.

La clave se guarda solo en tu ordenador (`voz\.env`), nunca en el repo. El plan gratis tiene un límite mensual de créditos y, según ElevenLabs, no incluye licencia comercial; compruébalo en su web. Si te quedas sin créditos o falla la conexión, Claude vuelve solo a la voz gratuita.

## Privacidad
- El audio se procesa en tu ordenador. Con ElevenLabs, solo se envía a ElevenLabs el texto que Claude va a decir.
- El dictado aprende tu huella de voz para ignorar a otras personas y el eco de Claude. Esos datos (`perfiles_voz.npz`, `muestras_voz/`) son biométricos, se quedan en tu equipo y están en `.gitignore`.

## Instalación manual
Requisitos: Windows 10/11, Python 3.12, micrófono. Mira `instalar.ps1`: cada paso está comentado. Para conectar Claude Code a mano, añade a `~/.claude/settings.json` un hook `Stop` que ejecute `voz/.venv/Scripts/python.exe voz/leer_ultima.py`, y pide en tu `CLAUDE.md` que Claude termine cada respuesta con una línea `VOZ: <resumen en una o dos frases>`.

## Desinstalar
Ejecuta `voz\parar.ps1` y `dictado\parar.ps1`, borra la carpeta y quita de `~/.claude/settings.json` las entradas que mencionan `leer_ultima.py` y `arrancar.ps1`, y de `~/.claude/CLAUDE.md` el bloque `speak-claude`. El instalador dejó copias `.bak-speak-claude` de esos dos archivos.

## Estado
Proyecto personal publicado tal cual: funciona a diario en el ordenador de su autor, pero no está probado en otros equipos. Si algo falla, abre un issue con el contenido de `dictado\dictado.log` y `voz\hook.log`. Las pruebas (`voz\pruebas.py`) paran y arrancan el servidor de voz y necesitan los modelos instalados.

## Créditos
Algunas ideas (filtro de eco por palabras, frases de espera, diagnóstico del silencio, detección de fin de turno) están inspiradas en otros proyectos de voz para asistentes; el código es propio. Voz Piper `es_ES-sharvard`, modelos Whisper (faster-whisper), Silero VAD y Smart Turn de sus autores, con sus licencias.

## Licencia
MIT. Ver [LICENSE](LICENSE).
