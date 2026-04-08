# claudevoice — Project Context for Claude

## What this repo is

A guide and hook scripts for enabling voice interaction with Claude Code on macOS:
- **VoiceMode plugin** — speak to Claude and hear responses via Kokoro TTS + Whisper STT
- **Voice confirmation hook** — approve/deny Claude's tool permission prompts by voice

## Key files

- `scripts/voice-confirm.py` — PermissionRequest hook; receives JSON on stdin, outputs decision JSON to stdout
- `scripts/install.sh` / `uninstall.sh` — automated setup/teardown
- `scripts/check-best-practices.sh` — project quality audit script
- `.claude/settings.json` — Claude Code config (hooks, permissions, plugins)

## Architecture

Voice services run as macOS LaunchAgents:
- Kokoro TTS: `http://127.0.0.1:8880`
- Whisper STT: `http://127.0.0.1:2022`

## Coding conventions

- Python 3.9+ compatible (no `list[...]` or `dict[...]` type hints — use `List`, `Dict` from `typing` or bare `list`/`dict`)
- No external Python dependencies — stdlib only in `voice-confirm.py`
- Bash scripts use `bash -n` syntax-checked, no `set -e` (explicit error handling preferred)
