# speak-claude: instalador guiado (Windows 10/11). Haz doble clic en instalar.cmd o ejecuta:
#   powershell -NoProfile -ExecutionPolicy Bypass -File instalar.ps1 [-SoloVoz] [-SinGPU]
# Instala Python si falta, crea los entornos, descarga los modelos, te ayuda con ElevenLabs (opcional),
# conecta Claude Code y arranca la voz. Casi todo se decide solo; las preguntas se contestan con Enter.
param([switch]$SoloVoz, [switch]$SinGPU)
$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $MyInvocation.MyCommand.Path

function Paso($t) { Write-Host "`n== $t" -ForegroundColor Cyan }
function Si($pregunta, $defecto = $true) {
    $sufijo = if ($defecto) { "[S/n]" } else { "[s/N]" }
    $r = (Read-Host "$pregunta $sufijo").Trim().ToLower()
    if ($r -eq "") { return $defecto }
    return $r -in @("s", "si", "sí", "y", "yes")
}
function Descarga($url, $destino) {
    if (Test-Path $destino) { return }
    New-Item -ItemType Directory -Force (Split-Path -Parent $destino) | Out-Null
    Write-Host "   descargando $(Split-Path -Leaf $destino)..."
    Invoke-WebRequest -Uri $url -OutFile $destino -UseBasicParsing
}
function PythonDe($carpeta) { Join-Path $raiz "$carpeta\.venv\Scripts\python.exe" }
function Entorno($carpeta, $paquetes) {
    $py = PythonDe $carpeta
    if (-not (Test-Path $py)) {
        Write-Host "   creando entorno de $carpeta..."
        & py -3.12 -m venv (Join-Path $raiz "$carpeta\.venv")
    }
    & $py -m pip install --quiet --disable-pip-version-check --upgrade pip
    & $py -m pip install --quiet --disable-pip-version-check @paquetes
    if ($LASTEXITCODE -ne 0) { throw "No se pudieron instalar las dependencias de $carpeta." }
}

Write-Host "speak-claude: Claude te habla y tú le hablas" -ForegroundColor Green

# 1. Python
Paso "1/5  Python"
$hayPython = $false
try { & py -3.12 -c "import sys" 2>$null; $hayPython = ($LASTEXITCODE -eq 0) } catch { }
if (-not $hayPython) {
    Write-Host "   Falta Python 3.12. Lo instalo con winget (Windows puede pedirte permiso una vez)."
    winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
    & py -3.12 -c "import sys" 2>$null
    if ($LASTEXITCODE -ne 0) { throw "No he podido instalar Python. Instálalo desde python.org y repite." }
}
Write-Host "   listo"

# 2. Voz de Claude
Paso "2/5  Voz de Claude (se queda en tu ordenador)"
Entorno "voz" @("piper-tts", "sounddevice", "soundfile", "numpy")
$hf = "https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_ES/sharvard/medium"
Descarga "$hf/es_ES-sharvard-medium.onnx" (Join-Path $raiz "voz\modelos\es_ES-sharvard-medium.onnx")
Descarga "$hf/es_ES-sharvard-medium.onnx.json" (Join-Path $raiz "voz\modelos\es_ES-sharvard-medium.onnx.json")
Write-Host "   listo"

# 3. Dictado
if (-not $SoloVoz) {
    Paso "3/5  Dictado por voz"
    $gpu = (-not $SinGPU) -and [bool](Get-Command nvidia-smi -ErrorAction SilentlyContinue)
    $paq = @("faster-whisper", "onnxruntime", "sounddevice", "numpy", "pynput", "pyperclip", "uiautomation", "pyaudiowpatch", "sherpa-onnx")
    if ($gpu) { $paq += @("nvidia-cublas-cu12", "nvidia-cudnn-cu12") }
    Entorno "dictado" $paq
    Descarga "https://huggingface.co/pipecat-ai/smart-turn-v3/resolve/main/smart-turn-v3.2-cpu.onnx" (Join-Path $raiz "dictado\modelos\smart-turn-v3.2-cpu.onnx")
    if (-not $gpu) {
        $cfg = Join-Path $raiz "dictado\config.json"
        $j = Get-Content $cfg -Raw | ConvertFrom-Json
        $j.dispositivo = "cpu"; $j.modelo = "small"
        $j | ConvertTo-Json -Depth 5 | Set-Content $cfg -Encoding UTF8
        Write-Host "   Sin tarjeta NVIDIA: dictado en CPU con un modelo más ligero."
    }
    Write-Host "   listo"
} else { Write-Host "`n== 3/5  Dictado: omitido (-SoloVoz)" }

# 4. ElevenLabs (opcional)
Paso "4/5  Voz más natural con ElevenLabs (opcional, hay plan gratis)"
Write-Host "   Sin esto Claude habla con una voz gratuita que ya funciona bien."
if (Si "   ¿Quieres probar ElevenLabs?" $false) {
    Write-Host "`n   Te abro la página de claves. Solo tienes que:"
    Write-Host "     1. Entrar o crear tu cuenta gratis."
    Write-Host "     2. Pulsar 'Create API Key' y luego 'Create' (con los permisos que vienen por defecto)."
    Write-Host "     3. Copiar la clave y volver aquí."
    Start-Process "https://elevenlabs.io/app/settings/api-keys"
    $hecho = $false
    for ($i = 1; $i -le 3 -and -not $hecho; $i++) {
        $seg = Read-Host "   Pega aquí la clave y pulsa Enter (no se verá al pegarla; Enter vacío para saltar)" -AsSecureString
        $clave = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($seg))
        if ($clave.Trim() -eq "") { Write-Host "   Saltado: seguirás con la voz gratuita."; break }
        $env:ELEVENLABS_API_KEY = $clave.Trim()
        & (PythonDe "voz") (Join-Path $raiz "voz\configurar_eleven.py")
        $codigo = $LASTEXITCODE
        Remove-Item Env:\ELEVENLABS_API_KEY -ErrorAction SilentlyContinue
        $clave = $null
        if ($codigo -eq 0) { $hecho = $true } elseif ($codigo -eq 3) { break }
    }
} else { Write-Host "   Vale, voz gratuita." }

# 5. Claude Code y arranque
Paso "5/5  Conectar con Claude Code y arrancar"
if (Si "   ¿Conecto Claude Code para que hable al terminar cada respuesta y arranque solo al abrirlo?") {
    & (PythonDe "voz") (Join-Path $raiz "registrar_claude.py") $raiz
}
$args2 = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $raiz "voz\arrancar.ps1"))
if ($SoloVoz) { $args2 += "-SinEscucha" }
& powershell @args2
Write-Host "`nListo. Abre Claude Code y escribe cualquier cosa: Claude te contestará hablando." -ForegroundColor Green
if (-not $SoloVoz) { Write-Host "El dictado tarda ~35 s en cargar la primera vez. F9 pausa o reanuda; F10 dos veces lo cierra." }
Write-Host "Para silenciar sin apagar: crea el archivo voz\SILENCIO. Más en README.md."
