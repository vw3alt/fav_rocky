# Rocky Desktop Buddy

A local, free, offline desktop companion inspired by Rocky from *Project Hail Mary*.
Talks to your girlfriend by voice, remembers facts about her over time, and shows
expressive pixel-art sprites while it "talks."

Everything runs **locally on her Mac** — no API keys, no per-message costs, no
internet dependency once set up (aside from the one-time downloads below).

```
rocky-project/
├── server/          <- Python "brain": LLM + memory + STT + TTS
│   ├── server.py
│   ├── requirements.txt
│   └── setup_mac.sh
└── electron/        <- Desktop pet UI
    ├── main.js
    ├── preload.js
    ├── index.html
    ├── renderer.js
    ├── package.json
    └── sprites/      <- placeholder art, swap for real Rocky pixel art
```

## What's already working here
- `/chat` — sends her message through the Rocky personality prompt, retrieves
  relevant memories from a local vector DB, returns a reply **and a mood tag**
  (happy/excited/curious/sad/worried/angry/idle) so the sprite can react.
- `/listen` — turns a recorded voice clip into text using faster-whisper
  (fully offline).
- `/speak` — turns Rocky's reply into speech using Piper TTS, then applies a
  pitch-shift pass for a heavier, alien-ish tone.
- `/remember` — lets you manually seed facts into memory if you want to give
  Rocky a head start (e.g. her name, favorite things) before first launch.
- Electron shell — transparent, draggable, always-on-top window that shows a
  sprite, listens for clicks, records her voice, and plays Rocky's response.

## What you still need to supply
1. **Real pixel art for Rocky.** I generated placeholder colored blobs in
   `electron/sprites/` just so the app runs out of the box — replace those
   PNG files (same filenames) with actual pixel art you create or commission.
   I can't generate Rocky's likeness myself since he's a copyrighted character
   from the book/movie, but a personal fan-art sprite you draw or have drawn
   is exactly the kind of thing this app is built to display.
2. One-time model downloads (handled by `setup_mac.sh`, see below).

---

## Setup on her Mac

### 1. Brain server
```bash
cd server
chmod +x setup_mac.sh
./setup_mac.sh
```
This installs Homebrew (if missing), Ollama, ffmpeg, sets up a Python venv,
installs dependencies, pulls the quantized Llama 3.1 8B model, and downloads
a Piper voice model.

Then start it:
```bash
source venv/bin/activate
python server.py
```
Leave this running in a terminal (or turn it into a background service later
via `launchd` once you're happy with it).

Check it's alive: open `http://localhost:8000/health` in a browser — you
should see `{"status": "ok", ...}`.

### 2. Desktop app
Requires Node.js (install via `brew install node` if not already present).
```bash
cd electron
npm install
npm start
```
Rocky should appear as a floating sprite in the bottom-right corner of her
screen. Click him to start recording, click again to stop and send.

---

## Building an installable app (from your Windows machine)

You don't need a Mac to build this — GitHub Actions can build the actual
macOS app for you for free. Rough steps:

1. Push this whole `rocky-project` folder to a GitHub repo (private is fine).
2. Add a workflow file at `.github/workflows/build-mac.yml` that runs on
   `macos-latest`, does `npm install` and `npm run build:mac` inside
   `electron/`, and uploads the resulting `.zip`/`.app` as a build artifact.
3. Download the artifact and send it to her (or have her download it
   directly from the Actions run).

I can write that workflow file for you next — just say the word once you've
got this running locally and want to package it up.

She'll still need the Python brain server + Ollama installed separately
(the `setup_mac.sh` script handles that in one shot) since bundling a full
LLM runtime into the Electron app itself is a heavier lift than it's worth
for a personal project like this.

---

## Tuning notes

- **Speed**: if replies still feel slow on her machine, try `phi3:mini` or
  `gemma2:2b` in `LLM_MODEL` inside `server.py` — much faster, still plenty
  capable for Rocky's short (5-20 word) lines.
- **Voice character**: `alienify()` in `server.py` currently just pitch-shifts
  and normalizes. If you want more of a "made of rock" texture, look into
  adding light ring modulation or bitcrushing — happy to add that next.
- **Memory**: everything gets stored in `server/rocky_memory/` (a local
  Chroma DB). Delete that folder any time to wipe Rocky's memory and start
  fresh. Use `/remember` to seed specific facts ahead of time.
- **Mood tags**: the LLM is instructed to prefix every reply with
  `[mood]`. If you swap models and moods stop showing up reliably, check the
  raw output from `/chat` in the terminal logs — some smaller models need a
  stricter prompt or a one-shot example to follow formatting instructions.

---

## Next steps (Phase 7 - screen vision)

Once the above is running smoothly, the next addition is a `/see` endpoint
using a local vision model (`ollama pull moondream` or `llava`), fed a
screenshot from Electron's `desktopCapturer` API plus her spoken question.
Say the word when you're ready and I'll wire that in too.
