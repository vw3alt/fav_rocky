const SERVER_URL = 'http://localhost:8000';
const USER_ID = 'girlfriend'; // change if you ever support multiple users

const rockyImg = document.getElementById('rocky');
const statusDot = document.getElementById('status-dot');

// Map Rocky's mood (from the LLM) + activity state to a sprite file.
// Drop your own pixel-art PNGs into the sprites/ folder with these names,
// or edit this map to point at whatever filenames you use.
const SPRITE_MAP = {
  idle: 'sprites/rest_bg.png',
  listening: 'sprites/point_bg.png',
  thinking: 'sprites/think_bg.png',
  talking_happy: 'sprites/rest_bg.png',
  talking_excited: 'sprites/hand_bg.png',
  talking_curious: 'sprites/point_bg.png',
  talking_sad: 'sprites/sad_bg.png',
  talking_worried: 'sprites/sad_bg.png',
  talking_angry: 'sprites/sad_bg.png',
  talking_idle: 'sprites/rest_bg.png',
};

// Hands-free voice activity detection settings
const SILENCE_THRESHOLD = 8;      // tweak based on her mic's noise floor
const SILENCE_DURATION_MS = 1200; // how long silence must persist to auto-stop
const FOLLOWUP_LISTEN_MS = 6000;  // how long Rocky waits for a follow-up after replying

let currentMood = 'idle';
let isRecording = false;
let mediaRecorder = null;
let audioChunks = [];

let audioContext, analyser, silenceTimer;

function setSprite(key) {
  const path = SPRITE_MAP[key] || SPRITE_MAP.idle;
  rockyImg.src = path;
}

function setStatus(state) {
  statusDot.className = state; // '', 'listening', 'thinking', 'talking'
}

async function recordUntilSilence() {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  mediaRecorder = new MediaRecorder(stream);
  audioChunks = [];
  mediaRecorder.ondataavailable = (e) => audioChunks.push(e.data);

  audioContext = new AudioContext();
  const source = audioContext.createMediaStreamSource(stream);
  analyser = audioContext.createAnalyser();
  analyser.fftSize = 512;
  source.connect(analyser);
  const data = new Uint8Array(analyser.frequencyBinCount);

  let hasHeardSpeech = false;

  function checkVolume() {
    analyser.getByteFrequencyData(data);
    const volume = data.reduce((a, b) => a + b, 0) / data.length;

    if (volume > SILENCE_THRESHOLD) {
      hasHeardSpeech = true;
      clearTimeout(silenceTimer);
      silenceTimer = setTimeout(() => stopRecording(), SILENCE_DURATION_MS);
    }
    if (isRecording) requestAnimationFrame(checkVolume);
  }

  mediaRecorder.onstop = () => {
    stream.getTracks().forEach((t) => t.stop());
    if (audioContext) audioContext.close();
    if (!hasHeardSpeech) {
      // nothing was said — go dormant instead of hitting the server
      setSprite('idle');
      setStatus('');
      isRecording = false;
      return;
    }
    handleRecordingStopped();
  };

  mediaRecorder.start();
  isRecording = true;
  setSprite('listening');
  setStatus('listening');
  checkVolume();

  // safety net: force-stop after 15s even if silence detection misbehaves
  silenceTimer = setTimeout(() => stopRecording(), 15000);
}

function stopRecording() {
  if (mediaRecorder && isRecording) {
    isRecording = false;
    mediaRecorder.stop();
  }
}

async function handleRecordingStopped() {
  setSprite('thinking');
  setStatus('thinking');

  const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });

  try {
    // 1. Speech -> text
    const form = new FormData();
    form.append('audio', audioBlob, 'clip.webm');
    const listenRes = await fetch(`${SERVER_URL}/listen`, { method: 'POST', body: form });
    const { text: heardText } = await listenRes.json();

    if (!heardText || !heardText.trim()) {
      setSprite('idle');
      setStatus('');
      return;
    }

    // 2. Text -> Rocky's reply + mood
    const chatRes = await fetch(`${SERVER_URL}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: USER_ID, message: heardText }),
    });
    const { response: replyText, mood } = await chatRes.json();
    currentMood = mood || 'idle';

    // 3. Text -> speech (Rocky's voice)
    setSprite(`talking_${currentMood}` in SPRITE_MAP ? `talking_${currentMood}` : 'talking_idle');
    setStatus('talking');

    const speakRes = await fetch(`${SERVER_URL}/speak`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: replyText }),
    });
    const audioArrayBuffer = await speakRes.arrayBuffer();
    const audioUrl = URL.createObjectURL(new Blob([audioArrayBuffer], { type: 'audio/wav' }));
    const audio = new Audio(audioUrl);

    audio.onended = () => {
      setSprite('idle');
      setStatus('');
      // Brief pause then open a follow-up listening window
      setTimeout(() => {
        recordUntilSilence();
      }, 300);
    };
    audio.play();

  } catch (err) {
    console.error('Rocky pipeline error:', err);
    setSprite('idle');
    setStatus('');
  }
}

// Click Rocky to wake him up (hands-free mode now)
rockyImg.addEventListener('click', () => {
  if (!isRecording) recordUntilSilence();
});

// Kick things off idle.
setSprite('idle');