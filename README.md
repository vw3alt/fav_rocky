# Rocky Desktop Buddy

Amaze! Amaze! Amaze!
fav_rocky is a free, local, offline desktop companion inspired by Rocky from *Project Hail Mary*.  It talks to you by voice, can remember facts, and can access your screen and camera (if allowed, and only when prompted).  Works on Windows & Mac.

Everything is local, so completely zero cost.  This comes at the tradeoff of time - it typically takes 10s for a regular reply, and 30s for an thinking one (e.g. if you request a task with the camera/screen).  Rocky will tell you "rocky thinking" if the reply will take some time.

Rocky does his best to infer, but if you want him to see your screen or camera, use the word "screen" or "camera" respectively to ensure he uses it.

```
FAV_ROCKY/
├── electron/                <- Desktop pet UI & main container
│   ├── node_modules/
│   ├── sprites/             <- Pixel art (feel free to make your own sprites!)
│   ├── index.html
│   ├── main.js
│   ├── package-lock.json
│   ├── package.json
│   ├── preload.js
│   ├── renderer.js
│   ├── rocky.ico
├── Rocky.app                     
├── server/                  <- Python "brain": LLM + memory + STT + TTS
│   ├── preload/
│   ├── venv/
│   ├── voices/
│   ├── requirements.txt
│   ├── rocky_facts.json     <- Local JSON memory for Rocky (JSON used over embeddings for easy editing)
│   ├── server.py
│   ├── setup_mac.sh
│   └── setup_windows.ps1
├── .gitignore                        
├── README.md                <- Documentation / instructions
├── Start Rocky.vbs          <- Click this to start Rocky!
├── start_rocky_windows.ps1           
└── start_rocky.sh                    
```

---

## Setup

Fist my bump!  Setup is simple:

### Initial (one-time) setup
[insert setup instructions here]

### Launch Rocky
Just double-click **Rocky.app**, and Rocky will load up in ~15 seconds!  There's a terminal to provide some visibility, but you can close it if desired.
To quit, just close the electron app (icon of Rocky).

---

## If you want to edit

- If replies feel very slow, try `phi3:mini` or `gemma2:2b` in `LLM_MODEL` inside `server.py`, or replace with your model of choice.
- `alienify()` in `server.py` is a pretty crude pitch shift, but does a decent job.
- The LLM is instructed to prefix every reply with `[mood]`. If you swap models and moods stop showing up reliably, check the raw output from `/chat` in the terminal logs — some smaller models need a stricter prompt or a one-shot example to follow formatting instructions.
- For manual start:
```bash
cd server && source venv/bin/activate && python server.py
# in another terminal:
cd electron && npm start
```

## Commands
- `/chat` — sends a message through the Rocky personality prompt, includes any remembered facts as context, returns a reply **and a mood tag** (happy/excited/curious/sad/worried/angry/idle) so the sprite can react.
- `/listen` — turns a recorded voice clip into text using faster-whisper (fully offline).
- `/speak` — turns Rocky's reply into speech using Piper TTS, then applies a pitch-shift pass for a heavier, rocky-ish tone.
- `/remember` — lets you manually seed facts into memory.
- Electron shell — transparent, draggable, always-on-top window that shows a sprite, listens for clicks, records voice, and plays Rocky's response.
