#!/usr/bin/env bash
# install.sh — Set up VoiceMode + voice confirmation hook for Claude Code
# Usage: bash scripts/install.sh
set -euo pipefail

CLAUDE_SETTINGS="$HOME/.claude/settings.json"
HOOK_SCRIPT="$HOME/.claude/voice-confirm.py"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()    { echo -e "${GREEN}[install]${NC} $*"; }
warn()    { echo -e "${YELLOW}[warn]${NC} $*"; }
error()   { echo -e "${RED}[error]${NC} $*" >&2; }

# ── Prerequisite checks ───────────────────────────────────────────────────────
check_prereqs() {
  local missing=()
  command -v python3 &>/dev/null || missing+=("python3")
  command -v jq      &>/dev/null || missing+=("jq (brew install jq)")
  command -v ffmpeg  &>/dev/null || missing+=("ffmpeg (brew install ffmpeg)")
  if [[ ${#missing[@]} -gt 0 ]]; then
    error "Missing prerequisites: ${missing[*]}"
    exit 1
  fi
  info "Prerequisites OK"
}

# ── Backup settings ───────────────────────────────────────────────────────────
backup_settings() {
  if [[ -f "$CLAUDE_SETTINGS" ]]; then
    local backup="${CLAUDE_SETTINGS}.bak.$(date +%Y%m%d_%H%M%S)"
    cp "$CLAUDE_SETTINGS" "$backup"
    info "Backed up settings to $backup"
  fi
}

# ── Install VoiceMode CLI and services ────────────────────────────────────────
install_voicemode() {
  if command -v voicemode &>/dev/null; then
    info "VoiceMode CLI already installed ($(voicemode --version 2>&1 | head -1))"
  else
    info "Installing VoiceMode CLI..."
    uvx voice-mode-install --yes
    export PATH="$HOME/.local/bin:$PATH"
  fi

  info "Installing Whisper STT service..."
  voicemode whisper service install || warn "Whisper may already be installed"

  info "Installing Kokoro TTS service..."
  voicemode kokoro install || warn "Kokoro may already be installed"

  info "Starting voice services..."
  voicemode whisper service start || warn "Whisper start failed — may already be running"
  voicemode kokoro start          || warn "Kokoro start failed — may already be running"
}

# ── Update ~/.claude/settings.json ───────────────────────────────────────────
update_settings() {
  if [[ ! -f "$CLAUDE_SETTINGS" ]]; then
    echo '{}' > "$CLAUDE_SETTINGS"
  fi

  local tmp
  tmp=$(mktemp)

  # Add marketplace
  jq '
    .extraKnownMarketplaces["voicemode"] = {
      "source": { "source": "github", "repo": "mbailey/voicemode" }
    }
  ' "$CLAUDE_SETTINGS" > "$tmp" && mv "$tmp" "$CLAUDE_SETTINGS"

  # Enable plugin
  jq '.enabledPlugins["voicemode@voicemode"] = true' \
    "$CLAUDE_SETTINGS" > "$tmp" && mv "$tmp" "$CLAUDE_SETTINGS"

  # Add permissions
  jq '
    if (.permissions.allow | index("mcp__voicemode__converse")) == null then
      .permissions.allow += ["mcp__voicemode__converse"]
    else . end |
    if (.permissions.allow | index("mcp__voicemode__service")) == null then
      .permissions.allow += ["mcp__voicemode__service"]
    else . end
  ' "$CLAUDE_SETTINGS" > "$tmp" && mv "$tmp" "$CLAUDE_SETTINGS"

  # Add PermissionRequest hook
  local hook_cmd="python3 ${HOOK_SCRIPT}"
  jq --arg cmd "$hook_cmd" '
    .hooks["PermissionRequest"] = [
      {
        "matcher": "",
        "hooks": [{ "type": "command", "command": $cmd }]
      }
    ]
  ' "$CLAUDE_SETTINGS" > "$tmp" && mv "$tmp" "$CLAUDE_SETTINGS"

  info "Updated ~/.claude/settings.json"
}

# ── Install hook script ───────────────────────────────────────────────────────
install_hook_script() {
  cp "$SCRIPT_DIR/voice-confirm.py" "$HOOK_SCRIPT"
  chmod +x "$HOOK_SCRIPT"
  info "Installed hook script to $HOOK_SCRIPT"
}

# ── Verify ────────────────────────────────────────────────────────────────────
verify() {
  local ok=true

  if command -v voicemode &>/dev/null; then
    info "voicemode CLI: OK"
  else
    warn "voicemode CLI: not found in PATH (may need to restart shell)"
    ok=false
  fi

  if curl -sf http://127.0.0.1:2022/health &>/dev/null; then
    info "Whisper STT: running"
  else
    warn "Whisper STT: not responding yet (may still be starting)"
    ok=false
  fi

  if curl -sf http://127.0.0.1:8880/ &>/dev/null; then
    info "Kokoro TTS: running"
  else
    warn "Kokoro TTS: not responding yet (may still be loading models)"
    ok=false
  fi

  if [[ -f "$HOOK_SCRIPT" ]]; then
    info "Hook script: $HOOK_SCRIPT"
  else
    error "Hook script not found at $HOOK_SCRIPT"
    ok=false
  fi

  if jq -e '.hooks.PermissionRequest' "$CLAUDE_SETTINGS" &>/dev/null; then
    info "PermissionRequest hook: registered"
  else
    error "PermissionRequest hook not found in settings.json"
    ok=false
  fi

  if $ok; then
    echo ""
    info "Install complete! Restart Claude Code for changes to take effect."
    echo ""
    echo "  Try voice conversation:   /voicemode:converse"
    echo "  Voice approvals:          trigger any tool approval prompt"
    echo ""
  else
    echo ""
    warn "Install completed with warnings. Check above and restart Claude Code."
  fi
}

# ── Main ──────────────────────────────────────────────────────────────────────
main() {
  echo "=== claudevoice installer ==="
  check_prereqs
  backup_settings
  install_voicemode
  install_hook_script
  update_settings
  verify
}

main "$@"
