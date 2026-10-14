# Para el dictado. -Todo: para tambien el vigilante (sin el, F9 ya no lo levanta).
param([switch]$Todo)
$base = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile = Join-Path $base 'dictado.pid'

if ($Todo) {
    Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' or Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like '*guardian.py*' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Remove-Item (Join-Path $base 'guardian.pid') -Force -ErrorAction SilentlyContinue
    Write-Output "VIGILANTE PARADO"
}

if (-not (Test-Path $pidFile)) {
    Write-Output "NO_ESTABA_ACTIVO"
    exit 0
}

$target = Get-Content $pidFile -ErrorAction SilentlyContinue
Remove-Item $pidFile -Force -ErrorAction SilentlyContinue

if ($target -and (Get-Process -Id $target -ErrorAction SilentlyContinue)) {
    Stop-Process -Id $target -Force
    Wait-Process -Id $target -Timeout 5 -ErrorAction SilentlyContinue
    Write-Output "PARADO $target"
} else {
    Write-Output "NO_ESTABA_ACTIVO"
}

# Por si quedo algun huerfano de un reinicio anterior (carrera al perder el pid file).
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' or Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like '*dictado.py*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
