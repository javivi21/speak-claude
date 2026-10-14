# Activa el dictado. -SinGuardian: no lanzar el vigilante (lo usa el propio vigilante).
param([switch]$SinGuardian)
$base = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile = Join-Path $base 'dictado.pid'
$python = Join-Path $base '.venv\Scripts\pythonw.exe'
if (-not (Test-Path $python)) { $python = Join-Path $base '.venv\Scripts\python.exe' }

# Vigilante (guardian.py, 03-oct): F9 vuelve a levantar el dictado aunque se cerrara con F10.
if (-not $SinGuardian) {
    $gPid = Get-Content (Join-Path $base 'guardian.pid') -ErrorAction SilentlyContinue
    if (-not ($gPid -and (Get-Process -Id $gPid -ErrorAction SilentlyContinue))) {
        Start-Process -FilePath $python -ArgumentList (Join-Path $base 'guardian.py') `
            -WorkingDirectory $base -WindowStyle Hidden
    }
}

if (Test-Path $pidFile) {
    $existing = Get-Content $pidFile -ErrorAction SilentlyContinue
    if ($existing -and (Get-Process -Id $existing -ErrorAction SilentlyContinue)) {
        Write-Output "YA_ACTIVO $existing"
        exit 0
    }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}

# -u obligatorio: sin consola, Python bufferia stdout y el log se queda vacio.
Start-Process -FilePath $python `
    -ArgumentList '-u', (Join-Path $base 'dictado.py') `
    -WorkingDirectory $base `
    -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $base 'dictado.log') `
    -RedirectStandardError (Join-Path $base 'dictado.err')

Write-Output "ARRANCANDO"
