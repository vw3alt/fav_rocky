# Rocky Brain Server - Windows setup (for local testing before deploying to Mac)
# Run this from PowerShell in the server/ folder:
#   powershell -ExecutionPolicy Bypass -File .\setup_windows.ps1

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Split-Path -Parent $ScriptDir   # setup_windows.ps1 lives in server/, project root is one level up
$ServerDir = $ScriptDir
$ElectronDir = Join-Path $ProjectDir "electron"

Write-Host "== Rocky Brain Server setup (Windows) ==" -ForegroundColor Cyan

if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Write-Host "Ollama not found. Download and install it from https://ollama.com/download/windows"
    Write-Host "Then re-run this script."
    exit 1
}

Write-Host "Pulling models (this is several GB total, be patient)..."
ollama pull gemma2:2b
ollama pull phi3:mini
ollama pull moondream
ollama pull llama3.1:8b-instruct-q4_K_M

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Host ""
    Write-Host "ffmpeg not found on PATH." -ForegroundColor Yellow
    Write-Host "Easiest fix: install via winget:"
    Write-Host "  winget install ffmpeg"
    Write-Host "Or via Chocolatey:"
    Write-Host "  choco install ffmpeg"
    Write-Host "Then re-run this script."
    exit 1
}

Write-Host "Setting up Python virtual environment..."
Push-Location $ServerDir
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt

New-Item -ItemType Directory -Force -Path voices | Out-Null

$joePath = "voices\en_US-joe-medium.onnx"
if (-not (Test-Path $joePath)) {
    Write-Host "Downloading Piper voice model (en_US-joe-medium)..."
    Invoke-WebRequest -Uri "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/joe/medium/en_US-joe-medium.onnx" -OutFile $joePath
    Invoke-WebRequest -Uri "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/joe/medium/en_US-joe-medium.onnx.json" -OutFile "$joePath.json"
}

$ryanPath = "voices\en_US-ryan-high.onnx"
if (-not (Test-Path $ryanPath)) {
    Write-Host "Downloading Piper voice model (en_US-ryan-high)..."
    Invoke-WebRequest -Uri "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/high/en_US-ryan-high.onnx" -OutFile $ryanPath
    Invoke-WebRequest -Uri "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/high/en_US-ryan-high.onnx.json" -OutFile "$ryanPath.json"
}
Pop-Location

if (-not (Test-Path (Join-Path $ElectronDir "node_modules"))) {
    Write-Host "Installing desktop widget dependencies..."
    Push-Location $ElectronDir
    npm install
    Pop-Location
}

Write-Host "Creating a desktop shortcut with Rocky's icon..."
$icoPath = Join-Path $ElectronDir "rocky.ico"

if (-not (Test-Path $icoPath)) {
    Write-Host "Couldn't find $icoPath -- shortcut will use a default icon." -ForegroundColor Yellow
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath("Desktop")) "Start Rocky.lnk"))
$shortcut.TargetPath = Join-Path $ProjectDir "Start Rocky.vbs"
$shortcut.WorkingDirectory = $ProjectDir
if (Test-Path $icoPath) {
    $shortcut.IconLocation = $icoPath
}
$shortcut.Save()

Write-Host ""
Write-Host "== Setup complete! ==" -ForegroundColor Green
Write-Host "A 'Start Rocky' shortcut with Rocky's icon has been added to your Desktop."
Write-Host "Double-click it any time to start Rocky."