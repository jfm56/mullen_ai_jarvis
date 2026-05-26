/**
 * Voice client: mic capture (via MediaRecorder) + audio playback.
 *
 * Browser support note: MediaRecorder is everywhere modern (Chrome/Edge/
 * Firefox/Safari 14.1+). The mime type we ask for varies by browser —
 * `audio/webm;codecs=opus` on Chromium, `audio/mp4` on Safari. faster-whisper
 * (which hands off to ffmpeg) sniffs the format from the bytes regardless.
 *
 * The recorder is single-instance per useRecorder() call. Start returns
 * a `stop()` that resolves to the captured Blob.
 */

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

const TOKEN_KEY = "jarvis_token";

function authHeader(): Record<string, string> {
  if (typeof window === "undefined") return {};
  const t = window.localStorage.getItem(TOKEN_KEY);
  return t ? { Authorization: `Bearer ${t}` } : {};
}

export interface VoiceStatus {
  stt_available: boolean;
  tts_available: boolean;
  notes: string;
}

export async function voiceStatus(): Promise<VoiceStatus> {
  const r = await fetch(`${API_BASE}/voice/status`, { headers: authHeader() });
  if (!r.ok) throw new Error(`voice/status failed: ${r.status}`);
  return (await r.json()) as VoiceStatus;
}

export async function transcribeBlob(blob: Blob, language = "en"): Promise<string> {
  const form = new FormData();
  form.append("audio", blob, `recording.${extFromMime(blob.type)}`);
  const url = `${API_BASE}/voice/transcribe?language=${encodeURIComponent(language)}`;
  const r = await fetch(url, {
    method: "POST",
    headers: authHeader(),
    body: form,
  });
  if (!r.ok) {
    const text = await r.text();
    throw new Error(`transcribe failed (${r.status}): ${text}`);
  }
  const json = (await r.json()) as { text: string };
  return json.text;
}

export async function speak(text: string): Promise<Blob> {
  const r = await fetch(`${API_BASE}/voice/speak`, {
    method: "POST",
    headers: { ...authHeader(), "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!r.ok) {
    const t = await r.text();
    throw new Error(`speak failed (${r.status}): ${t}`);
  }
  return await r.blob();
}

export async function playAudioBlob(blob: Blob): Promise<void> {
  const url = URL.createObjectURL(blob);
  const audio = new Audio(url);
  try {
    await audio.play();
    await new Promise<void>((resolve) => {
      audio.onended = () => resolve();
      audio.onerror = () => resolve();
    });
  } finally {
    URL.revokeObjectURL(url);
  }
}

function extFromMime(mime: string): string {
  if (mime.includes("webm")) return "webm";
  if (mime.includes("mp4") || mime.includes("m4a")) return "m4a";
  if (mime.includes("ogg")) return "ogg";
  if (mime.includes("wav")) return "wav";
  return "bin";
}

// ---- Recorder helper ------------------------------------------------------

export interface Recorder {
  start: () => Promise<void>;
  stop: () => Promise<Blob>;
  cancel: () => void;
  isRecording: () => boolean;
}

export function createRecorder(): Recorder {
  let mediaStream: MediaStream | null = null;
  let recorder: MediaRecorder | null = null;
  let chunks: Blob[] = [];
  let stopResolve: ((blob: Blob) => void) | null = null;
  let stopReject: ((err: unknown) => void) | null = null;
  let recording = false;

  // Pick a mime the browser actually supports. Chrome/Firefox: webm/opus.
  // Safari: mp4 (AAC) — we don't try to convert, just upload as-is.
  function pickMime(): string {
    const candidates = [
      "audio/webm;codecs=opus",
      "audio/webm",
      "audio/mp4",
      "audio/ogg;codecs=opus",
    ];
    for (const c of candidates) {
      if (typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported(c)) {
        return c;
      }
    }
    return "";
  }

  return {
    async start() {
      if (recording) return;
      if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia) {
        throw new Error("microphone API not available in this browser");
      }
      mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      chunks = [];
      const mime = pickMime();
      recorder = new MediaRecorder(mediaStream, mime ? { mimeType: mime } : undefined);
      recorder.ondataavailable = (ev: BlobEvent) => {
        if (ev.data && ev.data.size > 0) chunks.push(ev.data);
      };
      recorder.onstop = () => {
        const blob = new Blob(chunks, { type: recorder?.mimeType || "audio/webm" });
        mediaStream?.getTracks().forEach((t) => t.stop());
        mediaStream = null;
        recording = false;
        if (stopResolve) stopResolve(blob);
      };
      recorder.onerror = (ev) => {
        recording = false;
        mediaStream?.getTracks().forEach((t) => t.stop());
        mediaStream = null;
        if (stopReject) stopReject(ev);
      };
      recorder.start();
      recording = true;
    },
    stop() {
      if (!recorder || !recording) {
        return Promise.reject(new Error("not recording"));
      }
      return new Promise<Blob>((resolve, reject) => {
        stopResolve = resolve;
        stopReject = reject;
        recorder!.stop();
      });
    },
    cancel() {
      if (recorder && recording) {
        try {
          recorder.stop();
        } catch {
          // ignore
        }
      }
      mediaStream?.getTracks().forEach((t) => t.stop());
      mediaStream = null;
      recorder = null;
      chunks = [];
      recording = false;
    },
    isRecording() {
      return recording;
    },
  };
}
