#!/usr/bin/env python3
"""
voice-confirm.py — Claude Code PermissionRequest hook
Intercepts tool approval prompts and handles them via voice (TTS + STT).
Retries up to MAX_RETRIES times before falling back to keyboard input.

Services expected:
  Kokoro TTS: http://127.0.0.1:8880/v1/audio/speech
  Whisper STT: http://127.0.0.1:2022/v1/audio/transcriptions
"""

import json
import os
import subprocess
import sys
import tempfile
import urllib.request
import urllib.error

# ── Configuration ─────────────────────────────────────────────────────────────
TTS_URL = os.environ.get("VOICEMODE_TTS_URL", "http://127.0.0.1:8880/v1/audio/speech")
STT_URL = os.environ.get("VOICEMODE_STT_URL", "http://127.0.0.1:2022/v1/audio/transcriptions")
RECORD_SECONDS = int(os.environ.get("VOICE_CONFIRM_RECORD_SECS", "5"))
MAX_RETRIES = int(os.environ.get("VOICE_CONFIRM_MAX_RETRIES", "3"))
FFMPEG = os.environ.get("FFMPEG_PATH", "/opt/homebrew/bin/ffmpeg")
AFPLAY = "/usr/bin/afplay"

YES_KEYWORDS = {"yes", "yeah", "yep", "yup", "sure", "approve", "approved",
                "allow", "go", "proceed", "continue", "ok", "okay", "confirm",
                "affirmative", "correct", "right", "do it", "go ahead"}
NO_KEYWORDS  = {"no", "nope", "nah", "deny", "denied", "cancel", "stop",
                "abort", "reject", "rejected", "negative", "don't", "dont",
                "block", "refuse", "refused"}


def tts_speak(text: str) -> bool:
    """Synthesize text and play it. Returns True on success."""
    payload = json.dumps({
        "model": "kokoro",
        "input": text,
        "voice": "af_sky",
        "response_format": "mp3",
    }).encode()
    req = urllib.request.Request(
        TTS_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            audio_data = resp.read()
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(audio_data)
            tmp_path = f.name
        subprocess.run([AFPLAY, tmp_path], check=True, capture_output=True)
        os.unlink(tmp_path)
        return True
    except Exception:
        return False


def record_audio(duration: int) -> str | None:
    """Record audio for `duration` seconds. Returns path to wav file or None."""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        out_path = f.name
    try:
        result = subprocess.run(
            [
                FFMPEG, "-y",
                "-f", "avfoundation",
                "-i", ":0",
                "-t", str(duration),
                "-ar", "16000",
                "-ac", "1",
                out_path,
            ],
            capture_output=True,
            timeout=duration + 5,
        )
        if result.returncode != 0:
            return None
        return out_path
    except Exception:
        return None


def stt_transcribe(audio_path: str) -> str | None:
    """Send audio to Whisper STT. Returns transcription text or None."""
    try:
        with open(audio_path, "rb") as f:
            audio_bytes = f.read()

        boundary = "----VoiceConfirmBoundary"
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="audio.wav"\r\n'
            f"Content-Type: audio/wav\r\n\r\n"
        ).encode() + audio_bytes + (
            f"\r\n--{boundary}\r\n"
            f'Content-Disposition: form-data; name="model"\r\n\r\n'
            f"whisper-1\r\n"
            f"--{boundary}--\r\n"
        ).encode()

        req = urllib.request.Request(
            STT_URL,
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
        return result.get("text", "").strip().lower()
    except Exception:
        return None


def check_service(url: str) -> bool:
    """Quick health-check: returns True if the service root responds."""
    base = url.rsplit("/v1/", 1)[0] + "/"
    try:
        urllib.request.urlopen(base, timeout=2)
        return True
    except Exception:
        return False


def keyboard_confirm(prompt: str) -> bool:
    """Fallback: ask via keyboard on /dev/tty."""
    try:
        with open("/dev/tty", "r") as tty:
            sys.stderr.write(f"\n[voice-confirm] {prompt} [y/N]: ")
            sys.stderr.flush()
            answer = tty.readline().strip().lower()
        return answer in {"y", "yes"}
    except Exception:
        return False


def build_prompt(payload: dict) -> str:
    tool = payload.get("tool_name", "unknown tool")
    tool_input = payload.get("tool_input", {})

    if isinstance(tool_input, dict):
        cmd = tool_input.get("command") or tool_input.get("description") or ""
        if not cmd:
            # Generic: join first two values
            cmd = " ".join(str(v) for v in list(tool_input.values())[:2])
    else:
        cmd = str(tool_input)

    cmd = cmd[:200]  # cap length for TTS
    return f"{tool} wants to run: {cmd}. Do you approve?"


def decide(transcript: str) -> str | None:
    """Returns 'allow', 'deny', or None (unclear)."""
    words = set(transcript.lower().replace(",", " ").replace(".", " ").split())
    if words & YES_KEYWORDS:
        return "allow"
    if words & NO_KEYWORDS:
        return "deny"
    # Single-word check for partial matches
    for w in words:
        if any(kw in w for kw in YES_KEYWORDS):
            return "allow"
        if any(kw in w for kw in NO_KEYWORDS):
            return "deny"
    return None


def respond(behavior: str):
    out = {
        "hookSpecificOutput": {
            "hookEventName": "PermissionRequest",
            "decision": {"behavior": behavior},
        }
    }
    print(json.dumps(out))


def main():
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        # Pass-through: can't parse, let Claude Code handle normally
        sys.exit(0)

    prompt_text = build_prompt(payload)
    tts_ok = check_service(TTS_URL)
    stt_ok = check_service(STT_URL)

    if not tts_ok or not stt_ok:
        # Services down — keyboard fallback
        approved = keyboard_confirm(prompt_text)
        respond("allow" if approved else "deny")
        return

    for attempt in range(1, MAX_RETRIES + 1):
        retry_prefix = f"Attempt {attempt} of {MAX_RETRIES}. " if attempt > 1 else ""
        spoken = retry_prefix + prompt_text
        tts_speak(spoken)

        audio_path = record_audio(RECORD_SECONDS)
        if audio_path:
            transcript = stt_transcribe(audio_path)
            os.unlink(audio_path)
        else:
            transcript = None

        if transcript:
            decision = decide(transcript)
            if decision:
                # Confirm what we heard
                tts_speak(f"Heard: {transcript}. {'Approved.' if decision == 'allow' else 'Denied.'}")
                respond(decision)
                return

        # Unclear — retry
        if attempt < MAX_RETRIES:
            tts_speak("Sorry, I didn't catch that. Please say yes or no.")

    # All retries exhausted — keyboard fallback
    tts_speak("Falling back to keyboard input.")
    approved = keyboard_confirm(prompt_text)
    respond("allow" if approved else "deny")


if __name__ == "__main__":
    main()
