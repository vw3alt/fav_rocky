const SERVER_URL = 'http://localhost:8000';
const USER_ID = 'girlfriend'; // change if you ever support multiple users

const rockyImg = document.getElementById('rocky');
const statusDot = document.getElementById('status-dot');
const dragHandle = document.getElementById('drag-handle');

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
const SILENCE_THRESHOLD = 12;      // tweak based on her mic's noise floor
const SILENCE_DURATION_MS = 1700; // how long silence must persist to auto-stop
const FOLLOWUP_LISTEN_MS = 5000;  // how long Rocky waits for a follow-up after replying
const MAX_LISTEN_MS = 18000;      // hard stop no matter what, even mid-sentence

let isCancelled = false;
let currentMood = 'idle';
let isRecording = false;
let mediaRecorder = null;
let audioChunks = [];
let hardStopTimer;
let audioContext, analyser, silenceTimer;

// ============================================================
// Click-through toggle: makes the transparent parts of the window
// pass clicks through to whatever is behind it, while Rocky and the
// drag handle stay clickable. Fixes the "dead zone" around Rocky.
// ============================================================
document.addEventListener('mousemove', (e) => {
  const interactive = e.target.closest('#rocky, #drag-handle');
  window.rockyWindow.setIgnoreMouseEvents(!interactive);
});

// ============================================================
// Click Rocky to start listening, click again (while listening) to cancel.
// Dragging is now handled entirely by the OS via #drag-handle's
// -webkit-app-region: drag in index.html, so no manual drag math here.
// ============================================================
rockyImg.addEventListener('click', handleRockyClick);

function handleRockyClick() {
  if (isRecording) {
    cancelListening();
  } else {
    recordUntilSilence();
  }
}

function cancelListening() {
  clearTimeout(silenceTimer);
  clearTimeout(hardStopTimer);
  isCancelled = true;
  if (mediaRecorder && mediaRecorder.state !== 'inactive') {
    mediaRecorder.stop();
  } else {
    isRecording = false;
    setSprite('idle');
    setStatus('');
  }
}

const VISION_TRIGGER_RE = /\b(see|look|watch|screen|wearing|appearance|camera|picture|color|computer)\b/i;

let thinkingAudioBlob = null;

async function preloadThinkingSound() {
  try {
    const res = await fetch(`${SERVER_URL}/thinking-sound`);
    thinkingAudioBlob = await res.blob();
  } catch (e) {
    console.error('failed to preload thinking sound', e);
  }
}

function announceThinking() {
  if (!thinkingAudioBlob) return;
  const audio = new Audio(URL.createObjectURL(thinkingAudioBlob));
  audio.play();
}

async function captureWebcamFrame() {
  const stream = await navigator.mediaDevices.getUserMedia({
    video: { width: { ideal: 1280 }, height: { ideal: 720 } }
  });
  const video = document.createElement('video');
  video.srcObject = stream;
  video.muted = true;
  video.playsInline = true;

  await new Promise((resolve, reject) => {
    video.onloadedmetadata = resolve;
    video.onerror = reject;
  });
  await video.play();

  await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));

  const canvas = document.createElement('canvas');
  canvas.width = video.videoWidth || 1280;
  canvas.height = video.videoHeight || 720;
  canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
  console.log('webcam frame captured:', video.videoWidth, video.videoHeight);

  stream.getTracks().forEach((t) => t.stop());
  return canvas.toDataURL('image/png').split(',')[1];
}

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
    audioContext.close();
    clearTimeout(hardStopTimer);
    isRecording = false;

    if (isCancelled) {
      isCancelled = false;
      setSprite('idle');
      setStatus('');
      return;
    }
    if (!hasHeardSpeech) {
      setSprite('idle');
      setStatus('');
      return;
    }
    handleRecordingStopped();
  };

  mediaRecorder.start();
  isRecording = true;
  setSprite('listening');
  setStatus('listening');
  checkVolume();

  hardStopTimer = setTimeout(() => stopRecording(), MAX_LISTEN_MS);
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

    let screenImageB64 = null;
    let webcamImageB64 = null;

    if (VISION_TRIGGER_RE.test(heardText)) {
      announceThinking();
      setSprite('thinking');
      setStatus('thinking');
      try { screenImageB64 = await window.rockyVision.captureScreen(); }
      catch (e) { console.error('screen capture failed', e); }
      try { webcamImageB64 = await captureWebcamFrame(); }
      catch (e) { console.error('webcam capture failed', e); }
    }

    // 2. Text -> Rocky's reply + mood
    const chatRes = await fetch(`${SERVER_URL}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_id: USER_ID,
        message: heardText,
        screen_image_b64: screenImageB64,
        webcam_image_b64: webcamImageB64,
      }),
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

// Kick things off idle.
setSprite('idle');
preloadThinkingSound();