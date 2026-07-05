#!/bin/bash
# Run this ONCE to set up everything Rocky needs (brain server + desktop
# widget). After this finishes, just double-click Rocky.app to start Rocky
# from then on — no more terminal commands needed.
#
# Usage: chmod +x setup_mac.sh && ./setup_mac.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"   # setup_mac.sh lives in server/, project root is one level up
SERVER_DIR="$PROJECT_DIR/server"
ELECTRON_DIR="$PROJECT_DIR/electron"

echo "== Rocky setup =="

# 1. Homebrew (skip if already installed)
if ! command -v brew &> /dev/null; then
    echo "Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi

# 2. Ollama (runs the local LLMs)
if ! command -v ollama &> /dev/null; then
    echo "Installing Ollama..."
    brew install ollama
fi

echo "Starting Ollama service..."
brew services start ollama
sleep 2

# Pull every model server.py can use. gemma2:2b is the default fast chat
# model, phi3:mini is used automatically when a vision request comes in,
# and moondream powers the screen/webcam "vision" feature. llama3.1:8b is
# kept as an optional heavier backup model (edit LLM_MODEL in server.py to
# switch to it) — it's a multi-GB download, so this step can take a while.
echo "Pulling models (this is several GB total, be patient)..."
ollama pull gemma2:2b
ollama pull phi3:mini
ollama pull moondream
ollama pull llama3.1:8b-instruct-q4_K_M

# 3. ffmpeg (needed by pydub for audio processing)
if ! command -v ffmpeg &> /dev/null; then
    echo "Installing ffmpeg..."
    brew install ffmpeg
fi

# 4. Node.js (needed for the Electron desktop widget)
if ! command -v node &> /dev/null; then
    echo "Installing Node.js..."
    brew install node
fi

# 5. Python deps
echo "Setting up Python virtual environment..."
cd "$SERVER_DIR"
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 6. Piper voice models — both voices, since server.py defaults to
# en_US-joe-medium but en_US-ryan-high is kept available as an alternative
# (set PIPER_VOICE_MODEL in server.py, or as an env var, to switch).
mkdir -p voices
if [ ! -f "voices/en_US-joe-medium.onnx" ]; then
    echo "Downloading Piper voice model (en_US-joe-medium)..."
    curl -L -o voices/en_US-joe-medium.onnx \
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/joe/medium/en_US-joe-medium.onnx"
    curl -L -o voices/en_US-joe-medium.onnx.json \
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/joe/medium/en_US-joe-medium.onnx.json"
fi
if [ ! -f "voices/en_US-ryan-high.onnx" ]; then
    echo "Downloading Piper voice model (en_US-ryan-high)..."
    curl -L -o voices/en_US-ryan-high.onnx \
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/high/en_US-ryan-high.onnx"
    curl -L -o voices/en_US-ryan-high.onnx.json \
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/high/en_US-ryan-high.onnx.json"
fi

# 7. Electron desktop widget dependencies
echo "Installing desktop widget dependencies..."
cd "$ELECTRON_DIR"
npm install

# 8. Make the launcher script + app bundle executable, and put a copy of
# Rocky.app on the Desktop so it's easy to find and double-click.
chmod +x "$PROJECT_DIR/start_rocky.sh"
chmod +x "$PROJECT_DIR/Rocky.app/Contents/MacOS/Rocky"
cp -R "$PROJECT_DIR/Rocky.app" "$HOME/Desktop/Rocky.app" 2>/dev/null || true

echo ""
echo "== Setup complete! =="
echo "Rocky.app has been copied to your Desktop."
echo "From now on, just double-click Rocky.app on your Desktop to start Rocky."
echo "A Terminal window will open showing status — that's normal, just leave it be."
echo "To quit Rocky, use the tray icon near the clock in your menu bar."
