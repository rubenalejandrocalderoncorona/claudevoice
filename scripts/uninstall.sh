#!/usr/bin/env bash
# uninstall.sh — Remove VoiceMode + voice confirmation hook from Claude Code
# Usage: bash scripts/uninstall.sh [--full]
#   --full  Also removes ~/.voicemode/ (models, config, logs)
set -euo pipefail

CLAUDE_SETTINGS="$HOME/.claude/settings.json"
HOOK_SCRIPT="$HOME/.claude/voice-confirm.py"
FULL_REMOVE=false

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[uninstall]${NC} $*"; }
warn()  { echo -e "${YELLOW}[warn]${NC} $*"; }

for arg in "$@"; do
  [[ "$arg" == "--full" ]] && FULL_REMOVE=true
done

# ── Backup settings ───────────────────────────────────────────────────────────
backup_settings() {
  if [[ -f "$CLAUDE_SETTINGS" ]]; then
    local backup="${CLAUDE_SETTINGS}.bak.$(date +%Y%m%d_%H%M%S)"
    cp "$CLAUDE_SETTINGS" "$backup"
    info "Backed up settings to $backup"
  fi
}

# ── Remove hook from settings.json ───────────────────────────────────────────
remove_hook_from_settings() {
  if [[ ! -f "$CLAUDE_SETTINGS" ]]; then
    warn "settings.json not found — skipping"
    return
  fi

  local tmp
  tmp=$(mktemp)

  # Remove PermissionRequest hook
  jq 'del(.hooks.PermissionRequest)' "$CLAUDE_SETTINGS" > "$tmp" && mv "$tmp" "$CLAUDE_SETTINGS"
  info "Removed PermissionRequest hook from settings.json"

  # Remove voicemode permissions
  jq '
    .permissions.allow = (
      (.permissions.allow // []) |
      map(select(startswith("mcp__voicemode__") | not))
    )
  ' "$CLAUDE_SETTINGS" > "$tmp" && mv "$tmp" "$CLAUDE_SETTINGS"
  info "Removed voicemode permissions from settings.json"

  # Disable plugin
  jq '.enabledPlugins["voicemode@voicemode"] = false' \
    "$CLAUDE_SETTINGS" > "$tmp" && mv "$tmp" "$CLAUDE_SETTINGS"
  info "Disabled voicemode@voicemode plugin"

  # Remove marketplace entry
  jq 'del(.extraKnownMarketplaces.voicemode)' \
    "$CLAUDE_SETTINGS" > "$tmp" && mv "$tmp" "$CLAUDE_SETTINGS"
  info "Removed voicemode marketplace entry"
}

# ── Remove hook script ────────────────────────────────────────────────────────
remove_hook_script() {
  if [[ -f "$HOOK_SCRIPT" ]]; then
    rm "$HOOK_SCRIPT"
    info "Removed $HOOK_SCRIPT"
  else
    warn "Hook script not found at $HOOK_SCRIPT — already removed?"
  fi
}

# ── Stop and unload LaunchAgents ──────────────────────────────────────────────
stop_services() {
  local whisper_plist="$HOME/Library/LaunchAgents/com.voicemode.whisper.plist"
  local kokoro_plist="$HOME/Library/LaunchAgents/com.voicemode.kokoro.plist"

  for plist in "$whisper_plist" "$kokoro_plist"; do
    if [[ -f "$plist" ]]; then
      local label
      label=$(basename "$plist" .plist)
      launchctl unload "$plist" 2>/dev/null && info "Unloaded $label" || warn "$label was not loaded"
      rm "$plist"
      info "Removed $plist"
    fi
  done
}

# ── Optionally remove ~/.voicemode ───────────────────────────────────────────
remove_voicemode_dir() {
  if [[ -d "$HOME/.voicemode" ]]; then
    read -r -p "Remove ~/.voicemode/ (models, config, logs)? [y/N] " confirm
    if [[ "$confirm" =~ ^[Yy]$ ]]; then
      rm -rf "$HOME/.voicemode"
      info "Removed ~/.voicemode/"
    else
      info "Kept ~/.voicemode/ — remove manually if needed"
    fi
  fi
}

# ── Optionally uninstall VoiceMode CLI ───────────────────────────────────────
remove_voicemode_cli() {
  read -r -p "Uninstall voicemode CLI? [y/N] " confirm
  if [[ "$confirm" =~ ^[Yy]$ ]]; then
    uv tool uninstall voice-mode 2>/dev/null && info "Uninstalled voicemode CLI" \
      || warn "voicemode CLI not managed by uv — remove manually"
  fi
}

# ── Main ──────────────────────────────────────────────────────────────────────
main() {
  echo "=== claudevoice uninstaller ==="

  backup_settings
  remove_hook_from_settings
  remove_hook_script
  stop_services
  remove_voicemode_dir
  remove_voicemode_cli

  echo ""
  info "Uninstall complete. Restart Claude Code for changes to take effect."
}

main "$@"
