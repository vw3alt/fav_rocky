# Windows equivalent of start_rocky.sh, for local testing only (the actual
# deploy target is start_rocky.sh + Rocky.app on her Mac).
#
# Usage: powershell -ExecutionPolicy Bypass -File .\start_rocky_windows.ps1
# (or just double-click start_rocky_windows.bat, which runs this for you)

$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ServerDir = Join-Path $ProjectDir "server"
$ElectronDir = Join-Path $ProjectDir "electron"
$LogDir = Join-Path $env:TEMP "rocky_logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

Write-Host "== Starting Rocky (Windows test run) ==" -ForegroundColor Cyan

# 1. Make sure Ollama is running.
if (-not (Get-Process ollama -ErrorAction SilentlyContinue)) {
    Write-Host "Starting Ollama..."
    Start-Process -FilePath "ollama" -ArgumentList "serve" `
        -RedirectStandardOutput "$LogDir\ollama.log" `
        -RedirectStandardError "$LogDir\ollama_err.log" `
        -WindowStyle Hidden
    Start-Sleep -Seconds 2
}

# 2. Start the Python brain server in the background.
#    IMPORTANT: launch venv's python.exe DIRECTLY (not wrapped in a nested
#    powershell -NoExit) so $serverProcess.Id is python's actual PID. The
#    previous version wrapped it in a child shell, meaning Stop-Process at
#    the end only killed the wrapper - python server.py kept running as an
#    orphan, which is why conversation history never actually reset between
#    "sessions."
$pythonExe = Join-Path $ServerDir "venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    "Setup hasn't been run yet. Run setup_windows.ps1 from the server folder first." | Out-File "$LogDir\server_err.log" -Append
    exit 1
}

$serverProcess = Start-Process -FilePath $pythonExe -ArgumentList "server.py" `
    -WorkingDirectory $ServerDir `
    -RedirectStandardOutput "$LogDir\server.log" `
    -RedirectStandardError "$LogDir\server_err.log" `
    -WindowStyle Hidden -PassThru
Write-Host "Brain server booting (PID $($serverProcess.Id), logs at $LogDir)..."

# Open a separate window that just tails the server's log output, purely
# for live debugging. This window has no connection to the actual server
# process, so closing it does NOT stop Rocky.
$serverLogPath = "$LogDir\server.log"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Write-Host 'Rocky server log (closing this window is safe, Rocky keeps running)' -ForegroundColor Cyan; Get-Content -Path `"$serverLogPath`" -Wait"

try {
    # 3. Wait for the server to report healthy.
    Write-Host -NoNewline "Waking Rocky up"
    $ready = $false
    for ($i = 0; $i -lt 90; $i++) {
        try {
            Invoke-WebRequest -Uri "http://127.0.0.1:8000/health" -UseBasicParsing -TimeoutSec 1 | Out-Null
            $ready = $true
            break
        } catch {
            Write-Host -NoNewline "."
            Start-Sleep -Seconds 1
        }
    }
    Write-Host ""

    if (-not $ready) {
        "Brain server did not start in time." | Out-File "$LogDir\server_err.log" -Append
        exit 1
    }

    Write-Host "Rocky is awake! Opening the desktop widget..." -ForegroundColor Green
    Write-Host "(Close Rocky from the taskbar, same as any other app, when you're done.)"

    # 4. Launch the desktop widget. This blocks until Rocky is quit.
    Push-Location $ElectronDir
    npm start
    Pop-Location
}
finally {
    # try/finally (instead of code just placed after npm start) guarantees
    # this runs even if npm start throws, or the script is interrupted -
    # this is the second half of the orphan-process fix.
    Write-Host "Shutting down Rocky's brain server..."
    Stop-Process -Id $serverProcess.Id -Force -ErrorAction SilentlyContinue
    Write-Host "Rocky has closed."
}