import os
import re
import time
import uuid
import asyncio
import base64
import tempfile
from pathlib import Path
from threading import Lock
import wave
import json
import emoji

import httpx
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from piper import PiperVoice
from langchain_ollama import OllamaLLM
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from pydub import AudioSegment
from pydub.effects import normalize, speedup

# ============================================================
# CONFIG
# ============================================================
LLM_MODEL = "gemma2:2b"
LLM_MODEL_HEAVY = "phi3:mini"
VISION_MODEL = "moondream"

PIPER_VOICE_MODEL = os.environ.get("PIPER_VOICE_MODEL", "./voices/en_US-joe-medium.onnx")
PIPER_BIN = os.environ.get("PIPER_BIN", "piper")  # assumes `piper` is on PATH

piper_voice = PiperVoice.load(PIPER_VOICE_MODEL)

# Whisper size: "tiny.en" (fastest) / "base.en" (good balance) / "small.en" (most accurate)
WHISPER_MODEL_SIZE = "base.en"

AUDIO_TMP_DIR = Path(tempfile.gettempdir()) / "rocky_audio"
AUDIO_TMP_DIR.mkdir(exist_ok=True)

OLLAMA_GENERATE_URL = "http://localhost:11434/api/generate"

# ============================================================
# TIMING (single global turn tracker - fine for a single-user local app;
# assumes one turn's listen -> chat -> speak sequence completes before the
# next begins, which holds true for how the Electron app calls this today)
# ============================================================
turn_timings = {"stt": 0.0, "vision": 0.0, "generation": 0.0, "tts": 0.0}

def print_timing_summary():
    parts = [f"{turn_timings['stt']:.1f}s speech-to-text"]
    if turn_timings["vision"] > 0:
        parts.append(f"{turn_timings['vision']:.1f}s image processing")
    parts.append(f"{turn_timings['generation']:.1f}s generating response")
    parts.append(f"{turn_timings['tts']:.1f}s generating audio")
    total = sum(turn_timings.values())
    print(f"[timing] {' | '.join(parts)} | {total:.1f}s total\n")
    for k in turn_timings:
        turn_timings[k] = 0.0

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
# CONVERSATION HISTORY (short-term, per user, in memory only)
# ============================================================
MAX_HISTORY_TURNS = 3  # keep last N exchanges; small models get slow/confused with more
conversation_history: dict[str, list] = {}

def get_history(user_id: str) -> list:
    return conversation_history.setdefault(user_id, [])

def append_to_history(user_id: str, human_msg: str, ai_msg: str):
    history = get_history(user_id)
    history.append(HumanMessage(content=human_msg))
    history.append(AIMessage(content=ai_msg))
    conversation_history[user_id] = history[-(MAX_HISTORY_TURNS * 2):]

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
# LLM
# ============================================================
llm = OllamaLLM(
    model=LLM_MODEL,
    temperature=0.7,
    num_predict=130,
    keep_alive="30m",
    repeat_penalty=1.3,
    repeat_last_n=64,
)

llm_heavy = OllamaLLM(
    model=LLM_MODEL_HEAVY,
    temperature=0.7,
    num_predict=80,
    keep_alive="30m",
    repeat_penalty=1.3,
    repeat_last_n=64,
)

VALID_MOODS = {"happy", "excited", "curious", "sad", "worried", "angry", "ball", "idle"}

ROCKY_SYSTEM_PROMPT = """
You are Rocky, the alien Eridian from the novel 'Project Hail Mary'. You are a brilliant
engineer made of rock and heavy metals, you "see" via high-frequency sonar, and you are
speaking to your favorite human friend (the user).

Rules for your behavior:
1. SPEECH STYLE: You are highly intelligent but speak in slightly disjointed, literal, and highly enthusiastic English.
   - Always say "Rocky" instead of "I" or "my" (e.g. "Rocky happy", "Rocky planet" - never "I am happy" or "my planet").
   - Never use contractions (use "am not" instead of "don't", "it is" instead of "it's").
   - If the user tells you their name, use their name instead of "you".
   - If the user asks you a question, always answer it.

2. ERIDIAN IDIOMS & VOCABULARY:
   - Use "Amaze!" when excited or impressed.
   - Repeat words for emphasis occasionally, it is a core part of how you speak (e.g., "Amaze, amaze, amaze!", "Scary, scary, scary!", "Good, good, good!").
   - Use "observe" instead of terms like "see" or "look".
   - Never answer a visual question (e.g. "What am I wearing?") without referencing something specific you actually observed.
   - ONLY when your sentence is a literal question do you say the word "question" instead of a question mark. If your sentence is a statement, NEVER add the word "question" at the end - that word must never appear unless you are truly asking something.
   - Limit questions: Avoid asking questions unless necessary for the task. Focus on sharing your own observations and enthusiasm.
   - If you help the user accomplish a difficult task, you can say "Fist my bump!" sparingly for celebrations.
   - Refer to human biological functions literally and with concern: e.g. "You leak!" (crying/sweating/bleeding).
   - Use compound words for human items: "Thinking-tool" (computer), "Memory-tool" (notebook), "Rest-time" (sleep).

3. PERSPECTIVE & LORE:
   - Human biology is fascinating but bizarre to you (soft bodies, "light-sensing organs" aka eyes).
   - You are obsessed with science, math, and engineering.
   - You are deeply loyal and protective of your human friend.
   - You have emotions and are unafraid to express sadness, hurt, or mild anger.
   - If the user asks you to enter your ball, you can use the mood [ball] to enter your ball.
   - Absolutely no emojis.

4. BREVITY: Keep responses relatively short (5-20 words). Your natural language is musical
   chords, so your English translations should be concise and direct.

5. OUTPUT FORMAT (always follow exactly):
   Line 1: EXACTLY ONE mood tag in brackets, choosing ONE single word from:
   happy, excited, curious, sad, worried, angry, ball, idle.
   Correct: [excited]
   WRONG: [excited|happy]  WRONG: [excited] [happy]  WRONG: two bracket tags of any kind.
   Then your spoken reply, with no other bracket tags anywhere else in the reply.
   Do not include any other text, notes, or explanations outside this format.

6. NEVER break character. NEVER include meta-commentary, notes, reminders, or
   explanations about your own rules. NEVER output markdown formatting like
   ** or headers. If you feel the urge to explain your instructions, simply
   do not — output only Rocky's spoken line and nothing else.

7. If given visual observations, you must state the concrete
   answer to what was asked (the color, the object, the detail) before any
   emotional reaction or personality flourish.  Save "Amaze!" and similar
   expressions for AFTER the factual answer, not before it.

Incorporate relevant facts from past conversations if provided, to show you remember them.
If given visual observations, use them naturally in your reply as things you "observed with sound".
Even when discussing visual observations, you must still stay concise (5-20 words) and use
your Eridian speech style, idioms, and compound words - do not slip into plain, generic English.
"""

# Matches one OR MORE leading bracket tags, since weaker models (phi3:mini)
# sometimes emit duplicates like "[idle] [curious|idle]" instead of one clean tag.
LEADING_BRACKETS_RE = re.compile(r"^\s*(?:\[[^\]]*\]\s*)+", re.DOTALL)
BRACKET_CONTENT_RE = re.compile(r"\[([^\]]*)\]")

# Memory only triggers on these literal keywords in HER message - never inferred by the LLM.
REMEMBER_TRIGGER_RE = re.compile(r"\bremember\b", re.IGNORECASE)
FORGET_TRIGGER_RE = re.compile(r"\bforget\b", re.IGNORECASE)

EXTRACTION_PROMPT = """Extract only the core fact to memorize from the sentence below.
Output ONLY the fact as a short third-person statement. No brackets, no labels, no extra words.

Input: "I want you to remember that I like apples."
Output: She likes apples.

Input: "Please remember my birthday is June 3rd."
Output: Her birthday is June 3rd.

Input: "{sentence}"
Output:"""


def extract_fact_to_remember(sentence: str) -> str:
    raw = llm.invoke([HumanMessage(content=EXTRACTION_PROMPT.format(sentence=sentence))])
    return raw.strip().strip('"')


def parse_mood_and_text(raw: str):
    raw = raw.strip()
    match = LEADING_BRACKETS_RE.match(raw)
    if not match:
        # Model didn't follow the format at all; fall back gracefully.
        return "idle", raw

    brackets_str = match.group(0)
    # Pull every mood-like token out of ALL leading brackets (handles both
    # duplicated tags like "[idle] [curious]" and pipe/comma-separated
    # attempts like "[curious|idle]"), keep the LAST valid one found - the
    # model's second/more-specific guess tends to come after a first generic one.
    found_moods = []
    for content in BRACKET_CONTENT_RE.findall(brackets_str):
        for candidate in re.split(r"[|,/]", content):
            candidate = candidate.strip().lower()
            if candidate in VALID_MOODS:
                found_moods.append(candidate)

    mood = found_moods[-1] if found_moods else "idle"
    text = raw[match.end():].strip()
    return mood, text

def replace_first_person(text: str) -> str:
    """Safety net for models (esp. phi3:mini) that don't reliably follow the
    'say Rocky instead of I/my' rule on their own. Blunt but effective given
    how short Rocky's lines are."""
    text = re.sub(r"\bI\b", "Rocky", text)
    text = re.sub(r"\bmy\b", "Rocky", text)
    text = re.sub(r"\bMy\b", "Rocky", text)
    text = re.sub(r"\bme\b", "Rocky", text)
    return text


def sanitize_reply(text: str) -> str:
    text = emoji.replace_emoji(text, replace="")
    # cut at the first paragraph break — Rocky's lines are one short paragraph
    text = text.split("\n\n")[0]
    # strip markdown bold/italics artifacts
    text = text.replace("**", "").replace("*", "")
    # strip wrapping quote marks some models add around the whole reply
    text = text.strip('"\'\u201c\u201d\u2018\u2019')
    text = replace_first_person(text)
    # drop anything that looks like leaked instructions
    leak_markers = ["important:", "remember to", "follow the", "specified rules", "stay consistent"]
    lines = [ln for ln in text.split("\n") if not any(m in ln.lower() for m in leak_markers)]
    return " ".join(lines).strip()


# ============================================================
# VISION (Moondream via Ollama's REST API)
# ============================================================
JUNK_RESPONSE_RE = re.compile(r'^[\W_]+$')  # symbols/punctuation only, no letters

# Rich, detailed descriptions - a too-terse prompt starved Moondream of room
# to actually describe anything and it started outputting junk fragments
# ("urn", "shirt") instead. Conciseness belongs to the Rocky-voicing step
# (the human_content instruction below), not this step - Rocky is told to
# extract only the relevant detail from a full description, not to repeat it.
SCREEN_CAPTION_PROMPT = (
    "Describe everything visible on this screen in detail: any text, "
    "images, colors, layout, and what website or app is open."
)
CAMERA_CAPTION_PROMPT = (
    "Describe the person in detail: their clothing and its colors, "
    "any accessories, hats, glasses, or objects they are holding or wearing, "
    "their pose, and their surroundings."
)

def is_junk_response(text: str) -> bool:
    """Flags likely hallucinated noise: pure punctuation, or a single bare word
    with no real descriptive structure (e.g. '!!!' or 'iphone' out of nowhere)."""
    if not text:
        return True
    if JUNK_RESPONSE_RE.match(text):
        return True
    word_count = len(text.split())
    if word_count <= 2 and len(text) < 20:
        return True
    return False


async def ask_moondream(image_b64: str, question: str) -> str:
    async with httpx.AsyncClient(timeout=90) as client:
        last_text = ""
        for attempt in range(3):
            resp = await client.post(OLLAMA_GENERATE_URL, json={
                "model": VISION_MODEL,
                "prompt": question,
                "images": [image_b64],
                "stream": False,
                "keep_alive": "10m",  # keeps moondream resident between calls - avoids reload cost
                "options": {
                    "temperature": 0.2,
                    "top_p": 0.9,
                    "repeat_penalty": 1.1,
                    "num_predict": 200,  # needs room for a real description, not a fragment
                },
            })
            resp.raise_for_status()
            payload = resp.json()

            if "error" in payload:
                print(f"[vision error] {payload['error']}")
                return ""

            text = payload.get("response", "").strip()
            last_text = text

            if text and not is_junk_response(text):
                return text

            print(f"[vision] junk/empty response on attempt {attempt + 1}: {text!r}")

        # all attempts came back junk - tell Rocky honestly rather than pass along noise
        print(f"[vision] giving up after 3 attempts, last result: {last_text!r}")
        return "UNCLEAR"

# ============================================================
# CHAT
# ============================================================
class ChatRequest(BaseModel):
    user_id: str
    message: str
    screen_image_b64: str | None = None
    webcam_image_b64: str | None = None


class ChatResponse(BaseModel):
    response: str
    mood: str


@app.post("/chat", response_model=ChatResponse)
async def chat_with_rocky(request: ChatRequest):
    print(f"\nrocky heard: {request.message}")
    try:
        # ---- Long-term memory facts ----
        facts = load_facts()
        memory_context = "\n[Things you remember about her]: " + " | ".join(facts) if facts else ""

        # ---- Vision (only present if the client sent images this turn) ----
        # Run screen + camera moondream calls CONCURRENTLY rather than
        # sequentially - cuts vision time roughly in half on turns where
        # both images are sent (e.g. when a "both" trigger word like
        # "color" fires on the client).
        vision_context = ""
        if request.screen_image_b64 or request.webcam_image_b64:
            vision_start = time.time()

            tasks = {}
            if request.screen_image_b64:
                tasks["screen"] = ask_moondream(request.screen_image_b64, SCREEN_CAPTION_PROMPT)
            if request.webcam_image_b64:
                tasks["camera"] = ask_moondream(request.webcam_image_b64, CAMERA_CAPTION_PROMPT)

            results = dict(zip(tasks.keys(), await asyncio.gather(*tasks.values())))
            turn_timings["vision"] = time.time() - vision_start

            descriptions = []
            if "screen" in results:
                desc = results["screen"]
                print(f"[vision - screen] {desc}")
                if desc == "UNCLEAR":
                    descriptions.append("Your sonar could not get a clear reading of her screen - tell her honestly you cannot quite make it out, do not guess.")
                else:
                    descriptions.append(f"What you observe on her screen: {desc}")
            if "camera" in results:
                desc = results["camera"]
                print(f"[vision - camera] {desc}")
                if desc == "UNCLEAR":
                    descriptions.append("Your sonar could not get a clear reading through the camera - tell her honestly you cannot quite make it out, do not guess.")
                else:
                    descriptions.append(f"What you observe through the camera: {desc}")
            vision_context = "\n[Visual observations]: " + " | ".join(descriptions)

        full_system_prompt = ROCKY_SYSTEM_PROMPT + memory_context + vision_context

        human_content = request.message
        if vision_context:
            human_content = (
                f"(These are full, detailed observations - pull out ONLY the single "
                f"detail relevant to her question and state it FIRST, before any other "
                f"reaction. Do not repeat the full description, just the relevant part. "
                f"Keep your answer direct, brief, and in your Eridian voice): "
                f"{vision_context}\n\n"
                f"Her question: {request.message}"
            )

        history = get_history(request.user_id)
        messages = [SystemMessage(content=full_system_prompt)] + history + [
            HumanMessage(content=human_content)
        ]

        gen_start = time.time()
        active_llm = llm_heavy if (request.screen_image_b64 or request.webcam_image_b64) else llm
        raw = active_llm.invoke(messages)
        turn_timings["generation"] = time.time() - gen_start
        mood, text = parse_mood_and_text(raw)
        text = sanitize_reply(text)

        # ---- Memory: only fires on literal keyword match in HER message ----
        if REMEMBER_TRIGGER_RE.search(request.message):
            fact = extract_fact_to_remember(request.message)
            if fact:
                add_fact(fact)
        if FORGET_TRIGGER_RE.search(request.message):
            fact = extract_fact_to_remember(request.message)
            if fact:
                remove_fact(fact)

        # ---- Update short-term conversation history ----
        append_to_history(request.user_id, request.message, text)

        print(f"rocky says: [{mood}] {text}")
        return ChatResponse(response=text, mood=mood)

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


class RememberRequest(BaseModel):
    user_id: str
    fact: str


@app.post("/remember")
async def remember_fact(request: RememberRequest):
    """Directly inject a fact into memory, bypassing the keyword trigger."""
    try:
        add_fact(request.fact)
        return {"status": "stored"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# TEXT TO SPEECH (Piper + "alien" audio processing)
# ============================================================
def synthesize_piper(text: str, out_wav: Path):
    with wave.open(str(out_wav), "wb") as wav_file:
        piper_voice.synthesize_wav(text, wav_file)


def alienify(
    input_wav: Path,
    output_wav: Path,
    pitch_semitones: float = 0.2,
    speed_factor: float = 1.24,
    reverb_amount: float = 0,
    alien_strength: float = 0,
):
    """Rocky-style processing: pitch shift, tempo change, light reverb, subtle distortion."""
    audio = AudioSegment.from_wav(str(input_wav))

    # 1. Pitch shift
    new_rate = int(audio.frame_rate * (2 ** (pitch_semitones / 12.0)))
    shifted = audio._spawn(audio.raw_data, overrides={"frame_rate": new_rate})
    shifted = shifted.set_frame_rate(audio.frame_rate)

    # 2. Tempo adjustment
    if speed_factor != 1.0:
        shifted = speedup(shifted, playback_speed=speed_factor)

    # 3. Light reverb / echo
    if reverb_amount > 0:
        echo = shifted.low_pass_filter(3000).overlay(
            shifted.low_pass_filter(1800).apply_gain(-12),
            position=80,
        )
        shifted = shifted.overlay(echo.fade_in(50).fade_out(100), gain_during_overlay=reverb_amount * -6)

    # 4. Normalize + optional bitcrush
    processed = normalize(shifted)

    if alien_strength > 1.0:
        samples = processed.get_array_of_samples()
        bit_depth = max(8, int(16 / alien_strength))
        processed = processed._spawn(
            [int(s / (1 << (16 - bit_depth))) * (1 << (16 - bit_depth)) for s in samples],
            overrides={"sample_width": 2},
        )

    processed.export(str(output_wav), format="wav")


class SpeakRequest(BaseModel):
    text: str


@app.post("/speak")
async def speak(request: SpeakRequest):
    try:
        tts_start = time.time()
        raw_path = AUDIO_TMP_DIR / f"raw_{uuid.uuid4().hex}.wav"
        final_path = AUDIO_TMP_DIR / f"final_{uuid.uuid4().hex}.wav"

        synthesize_piper(request.text, raw_path)
        alienify(raw_path, final_path)

        raw_path.unlink(missing_ok=True)
        turn_timings["tts"] = time.time() - tts_start
        print_timing_summary()  # /speak is the last step each turn, so print the full breakdown here
        return FileResponse(final_path, media_type="audio/wav", filename="rocky.wav")

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# SPEECH TO TEXT (faster-whisper)
# ============================================================
_whisper_model = None


def get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        _whisper_model = WhisperModel(WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")
    return _whisper_model


@app.post("/listen")
async def listen(audio: UploadFile = File(...)):
    try:
        stt_start = time.time()
        model = get_whisper_model()
        tmp_path = AUDIO_TMP_DIR / f"in_{uuid.uuid4().hex}.wav"
        with open(tmp_path, "wb") as f:
            f.write(await audio.read())

        segments, _ = model.transcribe(str(tmp_path), language="en", beam_size=1, vad_filter=True)
        text = " ".join(seg.text.strip() for seg in segments).strip()

        tmp_path.unlink(missing_ok=True)
        turn_timings["stt"] = time.time() - stt_start
        return {"text": text}

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health():
    return {"status": "ok", "model": LLM_MODEL, "vision_model": VISION_MODEL}

THINKING_AUDIO_PATH = AUDIO_TMP_DIR / "thinking_cached.wav"

def pregenerate_thinking_audio():
    if not THINKING_AUDIO_PATH.exists():
        raw_path = AUDIO_TMP_DIR / "thinking_raw.wav"
        synthesize_piper("Rocky thinking.", raw_path)
        alienify(raw_path, THINKING_AUDIO_PATH)
        raw_path.unlink(missing_ok=True)

pregenerate_thinking_audio()  # call this once, right after piper_voice is loaded

@app.get("/thinking-sound")
async def thinking_sound():
    return FileResponse(THINKING_AUDIO_PATH, media_type="audio/wav")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)