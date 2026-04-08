# claudevoice — Quick Start

Get voice interaction + voice-based tool approvals working in Claude Code in under 5 minutes.

## Prerequisites

```bash
brew install ffmpeg jq
```

Python 3.9+ and Claude Code CLI must already be installed.

---

## Option A — Automated (recommended)

```bash
git clone <this-repo> claudevoice
cd claudevoice
bash scripts/install.sh
```

Restart Claude Code. Done.

---

## Option B — Manual (5 steps)

**1. Install VoiceMode CLI and services**

```bash
uvx voice-mode-install --yes
voicemode whisper service install
voicemode kokoro install
```

**2. Add VoiceMode to `~/.claude/settings.json`**

```json
{
  "extraKnownMarketplaces": {
    "voicemode": { "source": { "source": "github", "repo": "mbailey/voicemode" } }
  },
  "enabledPlugins": { "voicemode@voicemode": true },
  "permissions": {
    "allow": ["mcp__voicemode__converse", "mcp__voicemode__service"]
  }
}
```

**3. Copy the voice confirmation hook**

```bash
cp scripts/voice-confirm.py ~/.claude/voice-confirm.py
```

**4. Register the hook in `~/.claude/settings.json`**

```json
{
  "hooks": {
    "PermissionRequest": [
      {
        "matcher": "",
        "hooks": [{ "type": "command", "command": "python3 /Users/YOUR_USERNAME/.claude/voice-confirm.py" }]
      }
    ]
  }
}
```

**5. Restart Claude Code**

---

## What to expect

- **`/voicemode:converse`** — starts a voice conversation with Claude (speak, Claude replies via TTS)
- **Tool approvals** — when Claude asks "Do you want to proceed?", it speaks the command aloud and listens for "yes" or "no"
  - If no voice detected: retries 3 times, then falls back to keyboard prompt

---

## Revert everything

```bash
bash scripts/uninstall.sh
```
