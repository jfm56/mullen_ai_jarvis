"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  createRecorder,
  playAudioBlob,
  speak,
  transcribeBlob,
  voiceStatus,
  type Recorder,
} from "@/lib/voice";

interface Props {
  /** Called once the user's speech has been transcribed to text. */
  onTranscript: (text: string) => void;
  /**
   * Optional reply to speak aloud after the agent responds. Pass `null`
   * to skip TTS (handy when the caller wants to render the reply but not
   * play it).
   */
  replyText?: string | null;
}

/**
 * Push-to-talk button. Hold (or click to toggle) → records → release/click
 * → transcribes and hands the text up via `onTranscript`. If the parent
 * sets `replyText`, plays it through TTS once.
 *
 * Falls back to a disabled-but-explanatory state when the backend reports
 * /voice/status as unavailable (lib not installed, voice not configured).
 */
export function VoiceButton({ onTranscript, replyText }: Props) {
  const recorderRef = useRef<Recorder | null>(null);
  const [recording, setRecording] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [available, setAvailable] = useState<boolean | null>(null);
  const [ttsAvailable, setTtsAvailable] = useState(false);
  const [availabilityNotes, setAvailabilityNotes] = useState<string>("");
  const lastSpoken = useRef<string | null>(null);

  // Capability check on mount.
  useEffect(() => {
    let cancelled = false;
    voiceStatus()
      .then((s) => {
        if (cancelled) return;
        setAvailable(s.stt_available);
        setTtsAvailable(s.tts_available);
        setAvailabilityNotes(s.notes);
      })
      .catch(() => {
        if (cancelled) return;
        setAvailable(false);
        setAvailabilityNotes("could not reach /voice/status");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Speak the reply when the parent gives us one.
  useEffect(() => {
    // Only attempt TTS when the backend reports a usable voice — otherwise
    // every reply fires a guaranteed-400 /voice/speak request.
    if (!replyText || !ttsAvailable || replyText === lastSpoken.current) return;
    lastSpoken.current = replyText;
    speak(replyText)
      .then(playAudioBlob)
      .catch((err) => {
        // TTS failure is non-fatal — the text is already displayed.
        // eslint-disable-next-line no-console
        console.warn("tts failed:", err);
      });
  }, [replyText, ttsAvailable]);

  const startRecording = useCallback(async () => {
    if (recording || busy) return;
    setError(null);
    if (!recorderRef.current) recorderRef.current = createRecorder();
    try {
      await recorderRef.current.start();
      setRecording(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "could not start recording");
    }
  }, [recording, busy]);

  const stopRecording = useCallback(async () => {
    if (!recording || !recorderRef.current) return;
    setBusy(true);
    setRecording(false);
    try {
      const blob = await recorderRef.current.stop();
      if (blob.size < 1024) {
        setError("recording too short — try again");
        return;
      }
      const text = await transcribeBlob(blob);
      if (text.trim()) {
        onTranscript(text.trim());
      } else {
        setError("nothing transcribed — try speaking closer to the mic");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "transcription failed");
    } finally {
      setBusy(false);
    }
  }, [recording, onTranscript]);

  // Toggle on click; the hold-to-record gesture is also wired up via
  // pointer events for users who prefer it.
  const onClick = useCallback(() => {
    if (recording) {
      void stopRecording();
    } else {
      void startRecording();
    }
  }, [recording, startRecording, stopRecording]);

  if (available === false) {
    return (
      <div className="text-xs text-brand-500">
        🎙 Voice unavailable. {availabilityNotes}
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        onClick={onClick}
        disabled={busy || available === null}
        className={
          "btn " +
          (recording
            ? "bg-red-700 text-white hover:bg-red-800"
            : "btn-secondary")
        }
        aria-pressed={recording}
        aria-label={recording ? "Stop recording" : "Start recording"}
      >
        {recording ? "■ Stop" : busy ? "Transcribing…" : "🎙 Speak"}
      </button>
      {error && <span className="text-xs text-red-700">{error}</span>}
      {recording && (
        <span className="text-xs text-brand-500">Recording… click Stop to send.</span>
      )}
    </div>
  );
}
