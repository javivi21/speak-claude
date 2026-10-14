# Arranca la voz de Claude (servidor residente con Piper ya cargado).
# Uso:  powershell -NoProfile -ExecutionPolicy Bypass -File "...\voz\arrancar.ps1"
# -Silencioso: no saluda por voz (para el arranque automatico al abrir sesion).
# -SinEscucha: no arranca el dictado. Por defecto voz y escucha van juntas (03-oct):
# antes al abrir sesion solo arrancaba la voz y Claude hablaba pero no oia al usuario.
param([switch]$Silencioso, [switch]$SinEscucha)
$raiz = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $SinEscucha) {
    $act = Join-Path (Split-Path -Parent $raiz) "dictado\activar.ps1"
    # En un powershell aparte (ShellExecute, sin heredar handles): activar.ps1 lanza el
    # dictado con la salida redirigida y, si se llama aqui dentro, el dictado hereda la
    # salida de este script y quien lo llamo (el hook de inicio) no ve nunca el final.
    if (Test-Path $act) {
        Start-Process -FilePath "powershell.exe" -WindowStyle Hidden `
            -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$act`""
        Write-Output "ESCUCHA: lanzada"
    }
}
$pyw = Join-Path $raiz ".venv\Scripts\pythonw.exe"
$srv = Join-Path $raiz "servidor_voz.py"

function Responde {
    try {
        $c = New-Object Net.Sockets.TcpClient
        $c.Connect("127.0.0.1", 50321)
        $s = $c.GetStream()
        $b = [Text.Encoding]::UTF8.GetBytes('{"cmd":"ping"}')
        $s.Write($b, 0, $b.Length)
        $buf = New-Object byte[] 16
        $n = $s.Read($buf, 0, 16)
        $c.Close()
        return $n -gt 0
    } catch { return $false }
}

if (Responde) {
    Write-Output "VOZ YA ACTIVA"
    exit 0
}

Start-Process -FilePath $pyw -ArgumentList $srv -WorkingDirectory $raiz -WindowStyle Hidden
# el modelo Piper tarda unos segundos en cargar
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Milliseconds 500
    if (Responde) {
        if (-not $Silencioso) {
            & $pyw -c "import socket,json; s=socket.create_connection(('127.0.0.1',50321)); s.sendall(json.dumps({'cmd':'hablar','texto':'Voz de Claude activada.'}).encode()+b'\n'); s.recv(16)"
        }
        Write-Output "VOZ ACTIVA"
        exit 0
    }
}
Write-Output "ERROR: la voz no arranco"
exit 1
