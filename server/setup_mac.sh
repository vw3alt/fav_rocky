#!/bin/bash
# Run this once on her Mac to set up the Rocky brain server.
# Usage: chmod +x setup_mac.sh && ./setup_mac.sh

set -e

echo "== Rocky Brain Server setup =="

# 1. Homebrew (skip if already installed)
if ! command -v brew &> /dev/null; then
    echo "Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi

# 2. Ollama (runs the local LLM)
if ! command -v ollama &> /dev/null; then
    echo "Installing Ollama..."
    brew install ollama
fi

echo "Starting Ollama service..."
brew services start ollama
sleep 2

echo "Pulling quantized Llama 3.1 8B model (this is a few GB, be patient)..."
ollama pull llama3.1:8b-instruct-q4_K_M

# 3. ffmpeg (needed by pydub for audio processing)
if ! command -v ffmpeg &> /dev/null; then
    echo "Installing ffmpeg..."
    brew install ffmpeg
fi

# 4. Python deps
echo "Setting up Python virtual environment..."
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 5. Piper voice model
mkdir -p voices
if [ ! -f "voices/en_US-ryan-high.onnx" ]; then
    echo "Downloading Piper voice model (en_US-ryan-high)..."
    curl -L -o voices/en_US-ryan-high.onnx \
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/high/en_US-ryan-high.onnx"
    curl -L -o voices/en_US-ryan-high.onnx.json \
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/high/en_US-ryan-high.onnx.json"
fi

echo ""
echo "== Setup complete! =="
echo "To start the server:"
echo "  source venv/bin/activate"
echo "  python server.py"
