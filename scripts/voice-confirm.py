#!/usr/bin/env python3
"""
voice-confirm.py — Claude Code PermissionRequest hook
Intercepts tool approval prompts and handles them via voice (TTS + STT).
TTS and recording run concurrently to minimize latency.
Retries up to MAX_RETRIES times before falling back to auto-deny.

Services expected:
  Kokoro TTS: http://127.0.0.1:8880/v1/audio/speech
  Whisper STT: http://127.0.0.1:2022/v1/audio/transcriptions
"""

import json
import os
import subprocess
import sys
import tempfile
import threading
import urllib.request
import urllib.error
from typing import Optional

# ── Configuration ─────────────────────────────────────────────────────────────
TTS_URL = os.environ.get("VOICEMODE_TTS_URL", "http://127.0.0.1:8880/v1/audio/speech")
STT_URL = os.environ.get("VOICEMODE_STT_URL", "http://127.0.0.1:2022/v1/audio/transcriptions")
RECORD_SECONDS = int(os.environ.get("VOICE_CONFIRM_RECORD_SECS", "6"))
MAX_RETRIES = int(os.environ.get("VOICE_CONFIRM_MAX_RETRIES", "2"))
FFMPEG = os.environ.get("FFMPEG_PATH", "/opt/homebrew/bin/ffmpeg")
AFPLAY = "/usr/bin/afplay"

YES_KEYWORDS = {"yes", "yeah", "yep", "yup", "sure", "approve", "approved",
                "allow", "go", "proceed", "continue", "ok", "okay", "confirm",
                "affirmative", "correct", "right", "do it", "go ahead"}
NO_KEYWORDS  = {"no", "nope", "nah", "deny", "denied", "cancel", "stop",
                "abort", "reject", "rejected", "negative", "don't", "dont",
                "block", "refuse", "refused"}


def tts_fetch(text: str) -> Optional[bytes]:
    """Fetch TTS audio bytes from Kokoro. Returns None on failure."""
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
            return resp.read()
    except Exception:
        return None


def tts_play(audio_bytes: bytes):
    """Play audio bytes via afplay (blocking)."""
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        f.write(audio_bytes)
        tmp_path = f.name
    try:
        subprocess.run([AFPLAY, tmp_path], check=True, capture_output=True)
    finally:
        os.unlink(tmp_path)


def record_audio(duration: int) -> Optional[str]:
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


def stt_transcribe(audio_path: str) -> Optional[str]:
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
    """Quick health-check: returns True if the service root responds (any HTTP status)."""
    base = url.rsplit("/v1/", 1)[0] + "/"
    try:
        urllib.request.urlopen(base, timeout=2)
        return True
    except urllib.error.HTTPError:
        return True  # Got a response — service is up, path just doesn't exist
    except Exception:
        return False


READ_ONLY_CMDS = ("git ", "gh ", "cat ", "head ", "tail ", "ls ", "echo ",
                  "grep ", "find ", "curl -s", "curl -f",
                  "python3 -c \"import ast", "jq ", "wc ", "sort ",
                  "diff ", "which ", "type ")


def is_safe_readonly(command: str) -> bool:
    cmd = command.strip()
    return any(cmd.startswith(p) for p in READ_ONLY_CMDS)


def build_prompt(payload: dict) -> str:
    tool = payload.get("tool_name", "unknown tool")
    tool_input = payload.get("tool_input", {})

    if isinstance(tool_input, dict):
        cmd = tool_input.get("command") or tool_input.get("description") or ""
        if not cmd:
            cmd = " ".join(str(v) for v in list(tool_input.values())[:2])
    else:
        cmd = str(tool_input)

    cmd = cmd[:200]
    return f"{tool} wants to run: {cmd}. Say yes or no."


def decide(transcript: str) -> Optional[str]:
    """Returns 'allow', 'deny', or None (unclear)."""
    words = set(transcript.lower().replace(",", " ").replace(".", " ").split())
    if words & YES_KEYWORDS:
        return "allow"
    if words & NO_KEYWORDS:
        return "deny"
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
    sys.stdout.flush()


def keyboard_confirm(prompt_text: str):
    """Fall back to keyboard input on /dev/tty when voice fails."""
    try:
        with open("/dev/tty", "r") as tty:
            sys.stderr.write(f"\nVoice recognition failed. {prompt_text}\nApprove? [y/N]: ")
            sys.stderr.flush()
            answer = tty.readline().strip().lower()
        if answer in {"y", "yes"}:
            respond("allow")
        else:
            respond("deny")
    except Exception:
        respond("deny")


def speak_and_record(prompt_text: str) -> Optional[str]:
    """
    Fetch TTS audio, then play it and record simultaneously so the user
    can start speaking while audio is still playing. Returns wav path or None.
    """
    audio_bytes = tts_fetch(prompt_text)

    # Start recording immediately (overlap with TTS playback)
    record_result: list[Optional[str]] = [None]
    record_done = threading.Event()

    def do_record():
        record_result[0] = record_audio(RECORD_SECONDS)
        record_done.set()

    record_thread = threading.Thread(target=do_record, daemon=True)
    record_thread.start()

    # Play TTS if we got audio
    if audio_bytes:
        tts_play(audio_bytes)

    # Wait for recording to finish
    record_done.wait(timeout=RECORD_SECONDS + 6)
    return record_result[0]


def main():
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(0)

    prompt_text = build_prompt(payload)

    # Auto-approve safe read-only commands
    tool_input = payload.get("tool_input", {})
    if isinstance(tool_input, dict):
        cmd = tool_input.get("command", "")
        if is_safe_readonly(cmd):
            respond("allow")
            return

    tts_ok = check_service(TTS_URL)
    stt_ok = check_service(STT_URL)

    if not tts_ok or not stt_ok:
        # Services down — deny to avoid silent auto-approval
        respond("deny")
        return

    for attempt in range(1, MAX_RETRIES + 1):
        retry_prefix = f"Attempt {attempt} of {MAX_RETRIES}. " if attempt > 1 else ""
        audio_path = speak_and_record(retry_prefix + prompt_text)

        if audio_path:
            transcript = stt_transcribe(audio_path)
            os.unlink(audio_path)
        else:
            transcript = None

        if transcript:
            decision = decide(transcript)
            if decision:
                confirm_text = f"{'Approved.' if decision == 'allow' else 'Denied.'}"
                # Speak confirmation in background — don't block the response
                conf_bytes = tts_fetch(confirm_text)
                if conf_bytes:
                    threading.Thread(
                        target=tts_play, args=(conf_bytes,), daemon=True
                    ).start()
                respond(decision)
                return

        if attempt < MAX_RETRIES:
            # Speak retry prompt (blocking so user knows to try again)
            retry_audio = tts_fetch("Sorry, I didn't catch that. Please say yes or no.")
            if retry_audio:
                tts_play(retry_audio)

    # All retries exhausted — fall back to keyboard
    keyboard_confirm(prompt_text)


if __name__ == "__main__":
    main()
