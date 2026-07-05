#!/bin/bash
# Starts everything Rocky needs: Ollama, the Python brain server, and the
# Electron desktop widget. Quit Rocky from the menu-bar tray icon (or close
# the window) and this script will clean up the brain server behind it.
#
# You normally shouldn't need to run this directly — double-click Rocky.app
# instead. This script is what Rocky.app runs under the hood.

set -e
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER_DIR="$PROJECT_DIR/server"
ELECTRON_DIR="$PROJECT_DIR/electron"
LOG_DIR="/tmp/rocky_logs"
mkdir -p "$LOG_DIR"

echo "== Starting Rocky =="

# 1. Make sure Ollama is running. brew services keeps it running persistently
#    after setup, but start it defensively in case it isn't for some reason.
if ! pgrep -x "ollama" > /dev/null 2>&1; then
    echo "Starting Ollama..."
    (brew services start ollama > "$LOG_DIR/ollama.log" 2>&1) || \
        (ollama serve > "$LOG_DIR/ollama.log" 2>&1 &)
    sleep 2
fi

# 2. Start the Python brain server in the background.
if [ ! -d "$SERVER_DIR/venv" ]; then
    echo ""
    echo "It looks like setup hasn't been run yet."
    echo "Please run setup_mac.sh once from the server/ folder first, then try again."
    read -n 1 -s -r -p "Press any key to close this window..."
    exit 1
fi

cd "$SERVER_DIR"
source venv/bin/activate
python server.py > "$LOG_DIR/server.log" 2>&1 &
SERVER_PID=$!
echo "Brain server booting (PID $SERVER_PID, logs at $LOG_DIR/server.log)..."

# Open a separate Terminal window that just tails the server's log output,
# purely for live debugging. This window has no connection to the actual
# server process, so closing it does NOT stop Rocky.
osascript -e "tell application \"Terminal\" to do script \"echo 'Rocky server log (closing this window is safe, Rocky keeps running)'; tail -f '$LOG_DIR/server.log'\"" > /dev/null

cleanup() {
    echo ""
    echo "Shutting down Rocky's brain server..."
    kill "$SERVER_PID" 2>/dev/null || true
}
trap cleanup EXIT

# 3. Wait for the server to report healthy before opening the widget.
echo -n "Waking Rocky up"
READY=""
for i in $(seq 1 90); do
    if curl -s http://127.0.0.1:8000/health > /dev/null 2>&1; then
        READY="yes"
        break
    fi
    echo -n "."
    sleep 1
done
echo ""

if [ -z "$READY" ]; then
    echo "Rocky's brain server did not start in time. Check $LOG_DIR/server.log for details."
    read -n 1 -s -r -p "Press any key to close this window..."
    exit 1
fi

echo "Rocky is awake! Opening the desktop widget..."
echo "(Quit Rocky any time from the menu bar icon near the clock.)"

# 4. Launch the desktop pet. This blocks until Rocky is quit (via the tray
#    icon), at which point cleanup() above runs automatically and stops
#    the brain server too.
cd "$ELECTRON_DIR"
npm start

echo "Rocky has closed."