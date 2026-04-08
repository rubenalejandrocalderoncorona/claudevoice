# claudevoice

Voice interaction and voice-based tool approval for [Claude Code](https://claude.ai/code) on macOS.

This repo documents how to set up:
1. **VoiceMode** — talk to Claude Code and hear responses spoken back
2. **Voice Confirmation Hook** — approve or deny Claude's tool permission prompts by voice instead of typing

---

## Table of Contents

- [Quick Start](#quick-start)
- [Overview](#overview)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Manual Setup](#manual-setup)
  - [Phase 1 — Install VoiceMode Plugin](#phase-1--install-voicemode-plugin)
  - [Phase 2 — Install Local Voice Services](#phase-2--install-local-voice-services)
  - [Phase 3 — Grant Permissions](#phase-3--grant-permissions)
  - [Phase 4 — Voice Confirmation Hook](#phase-4--voice-confirmation-hook)
- [Reverting / Disabling](#reverting--disabling)
- [Configuration Reference](#configuration-reference)
- [Troubleshooting](#troubleshooting)

---

## Quick Start

> See [QUICKSTART.md](./QUICKSTART.md) for a 5-command setup guide.

Or run the automated installer:

```bash
bash scripts/install.sh
```

To revert everything:

```bash
bash scripts/uninstall.sh
```

---

## Overview

### VoiceMode (`/voicemode:converse`)

VoiceMode is a Claude Code plugin that adds real-time voice conversation support. Once set up, you can speak to Claude and hear responses — no typing required.

### Voice Confirmation Hook

Claude Code asks for approval before running potentially dangerous commands (Bash, file edits, etc.). By default this is a keyboard prompt. The voice confirmation hook intercepts those prompts and:

1. Speaks the command description aloud via TTS
2. Records your voice response
3. Transcribes it via STT
4. Automatically approves or denies based on what you said

This is implemented using Claude Code's `PermissionRequest` hook event.

---

## Architecture

```
Claude Code (CLI)
      │
      ├── MCP Plugin: voicemode@voicemode
      │     └── converse tool → Kokoro TTS + Whisper STT
      │
      └── PermissionRequest Hook
            └── voice-confirm.py
                  ├── Kokoro TTS  (http://127.0.0.1:8880)  ← speaks the prompt
                  └── Whisper STT (http://127.0.0.1:2022)  ← captures your response
```

### Services

| Service | Port | Purpose | Managed by |
|---------|------|---------|------------|
| Kokoro TTS | 8880 | Text-to-speech (local, GPU-accelerated) | launchd |
| Whisper STT | 2022 | Speech-to-text (local, OpenAI Whisper) | launchd |

Both services run as macOS LaunchAgents (auto-start on login, auto-restart on crash).

### Key Files

| Path | Purpose |
|------|---------|
| `~/.claude/settings.json` | Claude Code global config — plugins, permissions, hooks |
| `~/.claude/voice-confirm.py` | PermissionRequest hook script |
| `~/.voicemode/voicemode.env` | VoiceMode environment config |
| `~/Library/LaunchAgents/com.voicemode.whisper.plist` | Whisper service definition |
| `~/Library/LaunchAgents/com.voicemode.kokoro.plist` | Kokoro service definition |

---

## Prerequisites

- macOS (Apple Silicon or Intel)
- [Claude Code CLI](https://claude.ai/code) installed
- Python 3.9+
- `ffmpeg` (`brew install ffmpeg`)
- `jq` for the install/uninstall scripts (`brew install jq`)
- Internet access for initial model downloads (models are cached locally after first run)

---

## Manual Setup

### Phase 1 — Install VoiceMode Plugin

**1a. Register the VoiceMode marketplace in `~/.claude/settings.json`:**

```json
{
  "extraKnownMarketplaces": {
    "voicemode": {
      "source": {
        "source": "github",
        "repo": "mbailey/voicemode"
      }
    }
  }
}
```

**1b. Enable the plugin:**

```json
{
  "enabledPlugins": {
    "voicemode@voicemode": true
  }
}
```

**1c. In Claude Code, run the install command:**

```
/voicemode:install
```

This installs the VoiceMode CLI and local voice services.

Or manually via terminal:

```bash
uvx voice-mode-install --yes
voicemode whisper service install
voicemode kokoro install
```

---

### Phase 2 — Install Local Voice Services

The install script above handles this, but for reference:

```bash
# Install and start Whisper STT
voicemode whisper service install
voicemode whisper service start

# Install and start Kokoro TTS
voicemode kokoro install
voicemode kokoro start
```

Verify services are running:

```bash
curl -s http://127.0.0.1:2022/health        # Whisper
curl -s http://127.0.0.1:8880/              # Kokoro
```

Services are registered as LaunchAgents so they start automatically on login.

---

### Phase 3 — Grant Permissions

Claude Code requires explicit permission to call VoiceMode MCP tools without prompting. Add to `~/.claude/settings.json`:

```json
{
  "permissions": {
    "allow": [
      "mcp__voicemode__converse",
      "mcp__voicemode__service"
    ]
  }
}
```

Without this, Claude Code will ask for approval every time it calls a voice tool.

---

### Phase 4 — Voice Confirmation Hook

**4a. Copy the hook script:**

```bash
cp scripts/voice-confirm.py ~/.claude/voice-confirm.py
chmod +x ~/.claude/voice-confirm.py
```

**4b. Register the PermissionRequest hook in `~/.claude/settings.json`:**

```json
{
  "hooks": {
    "PermissionRequest": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python3 /Users/YOUR_USERNAME/.claude/voice-confirm.py"
          }
        ]
      }
    ]
  }
}
```

Replace `YOUR_USERNAME` with your actual macOS username.

**How the hook works:**

When Claude Code is about to run a tool that requires approval, instead of showing a `[y/N]` prompt, it calls `voice-confirm.py`. The script:

1. Receives a JSON payload on stdin describing the tool and its inputs
2. Synthesizes a spoken description via Kokoro TTS and plays it through `afplay`
3. Records 5 seconds of audio via `ffmpeg`
4. Sends the recording to Whisper STT for transcription
5. Matches the transcript against yes/no keyword lists
6. Returns a JSON decision (`allow` or `deny`) on stdout

If no clear response is detected, it retries up to 3 times. After all retries are exhausted, it falls back to a keyboard prompt on `/dev/tty`.

**Hook payload example (what the script receives on stdin):**

```json
{
  "tool_name": "Bash",
  "tool_input": {
    "command": "sed -n '1535,1560p' /path/to/file.js",
    "description": "Read lines from app.js"
  },
  "permission_mode": "default",
  "session_id": "abc123",
  "cwd": "/Users/you/project"
}
```

**Hook response format (what the script outputs to stdout):**

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PermissionRequest",
    "decision": {
      "behavior": "allow"
    }
  }
}
```

---

## Reverting / Disabling

### Disable only the voice confirmation hook

Remove the `hooks` section from `~/.claude/settings.json`:

```bash
jq 'del(.hooks)' ~/.claude/settings.json > /tmp/settings.tmp \
  && mv /tmp/settings.tmp ~/.claude/settings.json
```

### Disable VoiceMode plugin (keep services installed)

```bash
jq '.enabledPlugins["voicemode@voicemode"] = false' ~/.claude/settings.json \
  > /tmp/settings.tmp && mv /tmp/settings.tmp ~/.claude/settings.json
```

### Stop voice services (without uninstalling)

```bash
launchctl unload ~/Library/LaunchAgents/com.voicemode.whisper.plist
launchctl unload ~/Library/LaunchAgents/com.voicemode.kokoro.plist
```

Restart them:

```bash
launchctl load ~/Library/LaunchAgents/com.voicemode.whisper.plist
launchctl load ~/Library/LaunchAgents/com.voicemode.kokoro.plist
```

### Full uninstall

```bash
bash scripts/uninstall.sh
```

This removes:
- VoiceMode permissions from `~/.claude/settings.json`
- The PermissionRequest hook from `~/.claude/settings.json`
- Disables the plugin in `~/.claude/settings.json`
- Unloads and removes LaunchAgent plists
- Optionally removes `~/.voicemode/` (models + config)

---

## Configuration Reference

### voice-confirm.py environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `VOICEMODE_TTS_URL` | `http://127.0.0.1:8880/v1/audio/speech` | Kokoro TTS endpoint |
| `VOICEMODE_STT_URL` | `http://127.0.0.1:2022/v1/audio/transcriptions` | Whisper STT endpoint |
| `VOICE_CONFIRM_RECORD_SECS` | `5` | Seconds of audio to record per attempt |
| `VOICE_CONFIRM_MAX_RETRIES` | `3` | Number of retries before keyboard fallback |
| `FFMPEG_PATH` | `/opt/homebrew/bin/ffmpeg` | Path to ffmpeg binary |

Set these in `~/.voicemode/voicemode.env` or export them in your shell profile.

### VoiceMode service ports

Configured in `~/.voicemode/voicemode.env`:

| Variable | Default | Service |
|----------|---------|---------|
| `VOICEMODE_WHISPER_PORT` | `2022` | Whisper STT |
| `VOICEMODE_KOKORO_PORT` | `8880` | Kokoro TTS |
| `VOICEMODE_SERVE_PORT` | `8765` | VoiceMode HTTP MCP |

---

## Troubleshooting

### Voice confirmation isn't triggering

- Check that `hooks.PermissionRequest` is in `~/.claude/settings.json`
- Confirm the path in the hook command is absolute (not `~`)
- Run the script manually: `echo '{"tool_name":"Bash","tool_input":{"command":"ls"}}' | python3 ~/.claude/voice-confirm.py`

### No audio plays / TTS not working

```bash
curl -s http://127.0.0.1:8880/   # Should return something
voicemode kokoro status
voicemode kokoro start
```

### Voice not being transcribed / STT not working

```bash
curl -s http://127.0.0.1:2022/health   # Should return {"status":"ok"}
voicemode whisper service status
voicemode whisper service start
```

### ffmpeg not found

```bash
brew install ffmpeg
# Then update FFMPEG_PATH in voice-confirm.py or set the env var
```

### Microphone permission denied

Go to **System Settings → Privacy & Security → Microphone** and grant access to Terminal (or whichever app runs Claude Code).

### Hook falls back to keyboard every time

The script retries 3 times and falls back if it can't detect a clear yes/no. Check:
1. Is your microphone working? (`ffmpeg -f avfoundation -i ":0" -t 2 /tmp/test.wav`)
2. Is the STT service returning text? Check `~/.voicemode/logs/whisper/whisper.out.log`
3. Try increasing `VOICE_CONFIRM_RECORD_SECS` to `8` or `10`
