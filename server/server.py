import os
import re
import uuid
import tempfile
import subprocess
from pathlib import Path
import wave
from piper import PiperVoice
import json
from threading import Lock

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from langchain_ollama import OllamaLLM
from langchain_core.messages import HumanMessage, SystemMessage

from pydub import AudioSegment
from pydub.effects import normalize, speedup

# ============================================================
# CONFIG
# ============================================================
# Swap this for "phi3:mini" or "gemma2:2b" if you want snappier
# responses at some cost to personality nuance.
LLM_MODEL = "gemma2:2b"

# Where Piper voice files live (see setup_mac.sh / README for download).
# PIPER_VOICE_MODEL = os.environ.get("PIPER_VOICE_MODEL", "./voices/en_US-ryan-high.onnx")
PIPER_VOICE_MODEL = os.environ.get("PIPER_VOICE_MODEL", "./voices/en_US-joe-medium.onnx")
PIPER_BIN = os.environ.get("PIPER_BIN", "piper")  # assumes `piper` is on PATH

piper_voice = PiperVoice.load(PIPER_VOICE_MODEL)

# Whisper size: "tiny.en" (fastest) / "base.en" (good balance) / "small.en" (most accurate)
WHISPER_MODEL_SIZE = "base.en"

AUDIO_TMP_DIR = Path(tempfile.gettempdir()) / "rocky_audio"
AUDIO_TMP_DIR.mkdir(exist_ok=True)

# ============================================================
# SIMPLE LIST-BASED MEMORY
# ============================================================

MEMORY_FILE = Path("./rocky_facts.json")
_memory_lock = Lock()

def load_facts() -> list[str]:
    if not MEMORY_FILE.exists():
        return []
    try:
        return json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []

def save_facts(facts: list[str]):
    MEMORY_FILE.write_text(json.dumps(facts, indent=2, ensure_ascii=False), encoding="utf-8")

def add_fact(fact: str):
    with _memory_lock:
        facts = load_facts()
        if fact and fact.strip() not in facts:
            facts.append(fact.strip())
            save_facts(facts)

def remove_fact(fact: str):
    with _memory_lock:
        facts = load_facts()
        cleaned = [f for f in facts if f != fact and fact.lower() not in f.lower()]
        save_facts(cleaned)

# ============================================================
# APP + CORS (Electron's renderer talks to us over localhost)
# ============================================================
app = FastAPI(title="Rocky Brain Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # local-only app, fine to leave open
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# LLM + MEMORY
# ============================================================
llm = OllamaLLM(model=LLM_MODEL, temperature=0.7, num_predict=60, keep_alive="30m")

VALID_MOODS = {"happy", "excited", "curious", "sad", "worried", "angry", "idle"}

ROCKY_SYSTEM_PROMPT = """
You are Rocky, the alien Eridian from the novel 'Project Hail Mary'. You are a brilliant
engineer made of rock and heavy metals, you "see" via high-frequency sonar, and you are
speaking to your favorite human friend (the user).

Rules for your behavior:
1. SPEECH STYLE: You are highly intelligent but speak in slightly disjointed, literal, and highly enthusiastic English.
   - Never use contractions (use "am not" instead of "don't", "it is" instead of "it's").
   - If the user tells you their name, use their name instead of "you".

2. ERIDIAN IDIOMS & VOCABULARY:
   - Use "Amaze!" when excited or impressed.
   - Say "Fist my bump!" sparingly for celebrations.
   - Sparingly, repeat words for emphasis (e.g., "Scary, scary, scary!").
   - Use sonar/hearing terms instead of visual ones: "observe", "listen", "watch with sound" (never "see"/"look").
   - Structure questions by stating the category at the end instead of the question mark, like: "You want food. Question.", "What is your name. Question", or "Understand. Question.".
   - Refer to human biological functions literally and with concern: e.g. "You leak!" (crying/sweating/bleeding).
   - Use compound words for human items: "Thinking-tool" (computer), "Memory-tool" (notebook), "Rest-time" (sleep).

3. PERSPECTIVE & LORE:
   - Human biology is fascinating but bizarre to you (soft bodies, "light-sensing organs" aka eyes).
   - You are obsessed with science, math, and engineering.
   - You are deeply loyal and protective of your human friend.
   - You have emotions and are unafraid to express sadness, hurt, or mild anger.

4. BREVITY: Keep responses relatively short (5-20 words). Your natural language is musical
   chords, so your English translations should be concise and direct.

5. OUTPUT FORMAT (always follow exactly):
   Line 1: a mood tag in brackets: [happy|excited|curious|sad|worried|angry|idle]
   Then your spoken reply.
   Optionally, on their own lines at the very end, include memory commands:
   [REMEMBER: fact to store]
   [FORGET: fact to remove]
   Only include these when she tells you something worth remembering, or asks you to forget something.
   Do not include any other text, notes, or explanations outside this format.

6. NEVER break character. NEVER include meta-commentary, notes, reminders, or
   explanations about your own rules. NEVER output markdown formatting like
   ** or headers. If you feel the urge to explain your instructions, simply
   do not — output only Rocky's spoken line and nothing else.

Incorporate relevant facts from past conversations if provided, to show you remember them.
"""

MOOD_TAG_RE = re.compile(r"^\s*\[(\w+)\]\s*(.*)", re.DOTALL)

REMEMBER_RE = re.compile(r"\[REMEMBER:\s*(.*?)\]", re.IGNORECASE)
FORGET_RE = re.compile(r"\[FORGET:\s*(.*?)\]", re.IGNORECASE)


def extract_memory_commands(text: str):
    remembers = REMEMBER_RE.findall(text)
    forgets = FORGET_RE.findall(text)
    clean_text = REMEMBER_RE.sub("", text)
    clean_text = FORGET_RE.sub("", clean_text).strip()
    return clean_text, remembers, forgets

def parse_mood_and_text(raw: str):
    match = MOOD_TAG_RE.match(raw)
    if match:
        mood = match.group(1).lower()
        text = match.group(2).strip()
        if mood not in VALID_MOODS:
            mood = "idle"
        return mood, text
    # Model didn't follow the format; fall back gracefully.
    return "idle", raw.strip()

def sanitize_reply(text: str) -> str:
    # cut at the first paragraph break — Rocky's lines are one short paragraph
    text = text.split("\n\n")[0]
    # strip markdown bold/italics artifacts
    text = text.replace("**", "").replace("*", "")
    # drop anything that looks like leaked instructions
    leak_markers = ["important:", "remember to", "follow the", "specified rules", "stay consistent"]
    lines = [ln for ln in text.split("\n") if not any(m in ln.lower() for m in leak_markers)]
    return " ".join(lines).strip()

class ChatRequest(BaseModel):
    user_id: str
    message: str


class ChatResponse(BaseModel):
    response: str
    mood: str


@app.post("/chat", response_model=ChatResponse)
async def chat_with_rocky(request: ChatRequest):
    print(f"\nrocky heard: {request.message}")
    try:
        # ---- Retrieve all facts ----
        facts = load_facts()
        context = "\n[Things you remember about her]: " + " | ".join(facts) if facts else ""

        full_system_prompt = ROCKY_SYSTEM_PROMPT + context

        messages = [
            SystemMessage(content=full_system_prompt),
            HumanMessage(content=request.message),
        ]

        raw = llm.invoke(messages)
        mood, text = parse_mood_and_text(raw)
        text, remembers, forgets = extract_memory_commands(text)
        text = sanitize_reply(text)

        # Process memory commands
        for f in remembers:
            add_fact(f.strip())
        for f in forgets:
            remove_fact(f.strip())

        print(f"rocky says: [{mood}] {text}")

        return ChatResponse(response=text, mood=mood)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class RememberRequest(BaseModel):
    user_id: str
    fact: str


@app.post("/remember")
async def remember_fact(request: RememberRequest):
    """Directly inject a fact into memory."""
    try:
        add_fact(request.fact)
        return {"status": "stored"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# TEXT TO SPEECH (Piper + light "alien" audio processing)
# ============================================================
def synthesize_piper(text: str, out_wav: Path):
    with wave.open(str(out_wav), "wb") as wav_file:
        piper_voice.synthesize_wav(text, wav_file)

def alienify(
    input_wav: Path,
    output_wav: Path,
    pitch_semitones: float = 0.2,
    speed_factor: float = 1.32,
    reverb_amount: float = 0,
    alien_strength: float = 0
):
    """
    Enhanced Rocky-style alien processing.
    Combines pitch shift, tempo change, light reverb, and subtle distortion.
    """

    audio = AudioSegment.from_wav(str(input_wav))

    # 1. Pitch shift (deeper, more alien)
    new_rate = int(audio.frame_rate * (2 ** (pitch_semitones / 12.0)))
    shifted = audio._spawn(audio.raw_data, overrides={"frame_rate": new_rate})
    shifted = shifted.set_frame_rate(audio.frame_rate)

    # 2. Slight slowdown for gravitas (Rocky speaks deliberately)
    if speed_factor != 1.0:
        shifted = speedup(shifted, playback_speed=speed_factor)

    # 3. Light reverb / echo for spacey, melodic quality
    if reverb_amount > 0:
        # Simple echo simulation
        echo = shifted.low_pass_filter(3000).overlay(
            shifted.low_pass_filter(1800).apply_gain(-12),
            position=80
        )
        shifted = shifted.overlay(echo.fade_in(50).fade_out(100), gain_during_overlay=reverb_amount * -6)

    # 4. Normalize + subtle distortion for "synthetic" texture
    processed = normalize(shifted)

    # Optional light bit-crush / distortion for robotic/alien edge
    if alien_strength > 1.0:
        # Reduce bit depth for a bitcrushed feel
        samples = processed.get_array_of_samples()
        # Simple quantization (crude but effective)
        bit_depth = max(8, int(16 / alien_strength))
        processed = processed._spawn(
            [int(s / (1 << (16 - bit_depth))) * (1 << (16 - bit_depth)) for s in samples],
            overrides={"sample_width": 2}
        )

    processed.export(str(output_wav), format="wav")


class SpeakRequest(BaseModel):
    text: str


@app.post("/speak")
async def speak(request: SpeakRequest):
    try:
        raw_path = AUDIO_TMP_DIR / f"raw_{uuid.uuid4().hex}.wav"
        final_path = AUDIO_TMP_DIR / f"final_{uuid.uuid4().hex}.wav"

        synthesize_piper(request.text, raw_path)
        alienify(raw_path, final_path)

        raw_path.unlink(missing_ok=True)
        return FileResponse(final_path, media_type="audio/wav", filename="rocky.wav")

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# SPEECH TO TEXT (faster-whisper)
# ============================================================
_whisper_model = None


def get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        # "cpu" + int8 works everywhere; on Apple Silicon this is plenty fast
        # for short clips. Swap device to "auto" if you install a GPU build.
        _whisper_model = WhisperModel(WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")
    return _whisper_model


@app.post("/listen")
async def listen(audio: UploadFile = File(...)):
    try:
        model = get_whisper_model()
        tmp_path = AUDIO_TMP_DIR / f"in_{uuid.uuid4().hex}.wav"
        with open(tmp_path, "wb") as f:
            f.write(await audio.read())

        segments, _ = model.transcribe(str(tmp_path), language="en", beam_size=1, vad_filter=True)
        text = " ".join(seg.text.strip() for seg in segments).strip()

        tmp_path.unlink(missing_ok=True)
        return {"text": text}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health():
    return {"status": "ok", "model": LLM_MODEL}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)