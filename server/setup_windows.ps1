# Rocky Brain Server - Windows setup (for local testing before deploying to Mac)
# Run this from PowerShell in the server/ folder:
#   powershell -ExecutionPolicy Bypass -File .\setup_windows.ps1

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Split-Path -Parent $ScriptDir   # setup_windows.ps1 lives in server/, project root is one level up
$ServerDir = $ScriptDir
$ElectronDir = Join-Path $ProjectDir "electron"

Write-Host "== Rocky Brain Server setup (Windows) ==" -ForegroundColor Cyan

# 1. Check for Ollama
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Write-Host "Ollama not found. Download and install it from https://ollama.com/download/windows"
    Write-Host "Then re-run this script."
    exit 1
}

# Pull every model server.py can use. gemma2:2b is the default fast chat
# model, phi3:mini is used automatically when a vision request comes in,
# and moondream powers the screen/webcam "vision" feature. llama3.1:8b is
# kept as an optional heavier backup model (edit LLM_MODEL in server.py to
# switch to it) -- it's a multi-GB download, so this step can take a while.
Write-Host "Pulling models (this is several GB total, be patient)..."
ollama pull gemma2:2b
ollama pull phi3:mini
ollama pull moondream
ollama pull llama3.1:8b-instruct-q4_K_M

# 2. Check for ffmpeg (needed by pydub)
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

# 3. Python venv + deps
Write-Host "Setting up Python virtual environment..."
Push-Location $ServerDir
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt

# 4. Piper voice models -- both voices, since server.py defaults to
# en_US-joe-medium but en_US-ryan-high is kept available as an alternative
# (set PIPER_VOICE_MODEL in server.py, or as an env var, to switch).
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

# 5. Electron desktop widget dependencies
if (-not (Test-Path (Join-Path $ElectronDir "node_modules"))) {
    Write-Host "Installing desktop widget dependencies..."
    Push-Location $ElectronDir
    npm install
    Pop-Location
}

# 6. Generate a proper .ico from Rocky's sprite, and create a desktop
# shortcut to "Start Rocky.vbs" using it. .vbs files can't carry a custom
# icon themselves, but a shortcut to one can -- this is what lets a
# double-clickable "Start Rocky" launcher show Rocky's own picture instead
# of a generic script icon.
Write-Host "Creating a desktop shortcut with Rocky's icon..."
$spritePath = Join-Path $ElectronDir "sprites\rest_bg.png"
$icoPath = Join-Path $ProjectDir "rocky.ico"

if (Test-Path $spritePath) {
    Add-Type -AssemblyName System.Drawing
    $bitmap = [System.Drawing.Bitmap]::FromFile($spritePath)
    $hIcon = $bitmap.GetHicon()
    $icon = [System.Drawing.Icon]::FromHandle($hIcon)
    $stream = [System.IO.File]::Create($icoPath)
    $icon.Save($stream)
    $stream.Close()
    $icon.Dispose()
    $bitmap.Dispose()
} else {
    Write-Host "Couldn't find $spritePath -- skipping icon generation, shortcut will use a default icon." -ForegroundColor Yellow
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