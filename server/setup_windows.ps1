# Rocky Brain Server - Windows setup (for local testing before deploying to Mac)
# Run this from PowerShell in the server/ folder:
#   powershell -ExecutionPolicy Bypass -File .\setup_windows.ps1

Write-Host "== Rocky Brain Server setup (Windows) ==" -ForegroundColor Cyan

# 1. Check for Ollama
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Write-Host "Ollama not found. Download and install it from https://ollama.com/download/windows"
    Write-Host "Then re-run this script."
    exit 1
}

Write-Host "Pulling quantized Llama 3.1 8B model (a few GB, be patient)..."
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
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt

# 4. Piper voice model
New-Item -ItemType Directory -Force -Path voices | Out-Null
$voicePath = "voices\en_US-ryan-high.onnx"
if (-not (Test-Path $voicePath)) {
    Write-Host "Downloading Piper voice model (en_US-ryan-high)..."
    Invoke-WebRequest -Uri "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/high/en_US-ryan-high.onnx" -OutFile $voicePath
    Invoke-WebRequest -Uri "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/high/en_US-ryan-high.onnx.json" -OutFile "$voicePath.json"
}

Write-Host ""
Write-Host "== Setup complete! ==" -ForegroundColor Green
Write-Host "To start the server:"
Write-Host "  .\venv\Scripts\Activate.ps1"
Write-Host "  python server.py"
