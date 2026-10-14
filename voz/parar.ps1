# Para la voz de Claude (cierra el servidor residente).
# Uso:  powershell -NoProfile -ExecutionPolicy Bypass -File "...\voz\parar.ps1"
$raiz = Split-Path -Parent $MyInvocation.MyCommand.Path
$marca = Join-Path $raiz "HABLANDO"

$pids = @()

# 1) el que tiene el puerto abierto (lo mas fiable)
$pids += (netstat -ano | Select-String ':50321\s+.*LISTENING' |
    ForEach-Object { ($_ -split '\s+')[-1] })

# 2) y cualquier proceso del servidor (incluye el lanzador del entorno)
$pids += (Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -like "*servidor_voz*" } |
    ForEach-Object { $_.ProcessId })

$parados = 0
foreach ($p in ($pids | Sort-Object -Unique)) {
    if ($p) { Stop-Process -Id $p -Force -ErrorAction SilentlyContinue; $parados++ }
}

if (Test-Path $marca) { Remove-Item $marca -Force -ErrorAction SilentlyContinue }

if ($parados -gt 0) { Write-Output "VOZ PARADA ($parados proceso/s)" }
else { Write-Output "NO HABIA VOZ ACTIVA" }
