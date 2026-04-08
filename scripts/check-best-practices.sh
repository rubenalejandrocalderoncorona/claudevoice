#!/usr/bin/env bash
# check-best-practices.sh — Audit this repo for Claude Code project best practices

PASS=0
FAIL=0
WARN=0

pass() { echo "  [PASS] $1"; ((PASS++)); }
fail() { echo "  [FAIL] $1"; ((FAIL++)); }
warn() { echo "  [WARN] $1"; ((WARN++)); }

echo "=== Claude Code Project Best Practices Checker ==="
echo ""

# ── Documentation ──────────────────────────────────────────────────────────────
echo "── Documentation ──"

if [ -f README.md ]; then pass "README.md exists"; else fail "README.md missing"; fi
[ -f QUICKSTART.md ] && pass "QUICKSTART.md exists" || warn "QUICKSTART.md missing (nice to have)"

# README has key sections
for section in "Prerequisites" "Installation|Quick Start|Setup" "Troubleshooting"; do
  grep -qiE "$section" README.md 2>/dev/null \
    && pass "README has '$section' section" \
    || warn "README missing '$section' section"
done

echo ""

# ── Claude Code Config ─────────────────────────────────────────────────────────
echo "── Claude Code Config (.claude/) ──"

[ -d .claude ] && pass ".claude/ directory exists" || fail ".claude/ directory missing"
[ -f .claude/settings.json ] && pass ".claude/settings.json exists" || fail ".claude/settings.json missing"

if [ -f .claude/settings.json ]; then
  # Valid JSON
  python3 -c "import json, sys; json.load(open('.claude/settings.json'))" 2>/dev/null \
    && pass ".claude/settings.json is valid JSON" \
    || fail ".claude/settings.json is invalid JSON"

  # Has hooks configured
  python3 -c "import json; d=json.load(open('.claude/settings.json')); assert 'hooks' in d" 2>/dev/null \
    && pass ".claude/settings.json has hooks configured" \
    || warn ".claude/settings.json missing hooks (optional but expected for this project)"
fi

# CLAUDE.md
[ -f CLAUDE.md ] && pass "CLAUDE.md exists (project instructions for Claude)" \
  || warn "CLAUDE.md missing — consider adding project context for Claude"

echo ""

# ── Git Hygiene ────────────────────────────────────────────────────────────────
echo "── Git Hygiene ──"

[ -f .gitignore ] && pass ".gitignore exists" || fail ".gitignore missing"

if [ -f .gitignore ]; then
  for pattern in ".env" "*.pyc" "__pycache__" ".DS_Store"; do
    grep -qF "$pattern" .gitignore \
      && pass ".gitignore covers '$pattern'" \
      || warn ".gitignore missing '$pattern'"
  done
fi

# No secrets patterns in tracked files
if git rev-parse --git-dir > /dev/null 2>&1; then
  pass "Directory is a git repository"

  # Check for accidental secrets
  if git ls-files | xargs grep -lE "(password|secret|api_key|token)\s*=" 2>/dev/null | grep -qvE "(README|QUICKSTART|\.md$)"; then
    fail "Possible hardcoded secrets found in tracked files"
  else
    pass "No obvious hardcoded secrets in tracked files"
  fi

  # Uncommitted changes
  if git diff --quiet && git diff --cached --quiet; then
    pass "Working tree is clean (no uncommitted changes)"
  else
    warn "Uncommitted changes present"
  fi
else
  fail "Not a git repository"
fi

echo ""

# ── Scripts ────────────────────────────────────────────────────────────────────
echo "── Scripts ──"

for script in scripts/install.sh scripts/uninstall.sh scripts/voice-confirm.py; do
  if [ -f "$script" ]; then
    pass "$script exists"
    [ -x "$script" ] && pass "$script is executable" || warn "$script is not executable"
  else
    warn "$script missing"
  fi
done

# Python syntax check
if command -v python3 &>/dev/null; then
  for pyfile in scripts/*.py; do
    [ -f "$pyfile" ] || continue
    python3 -m py_compile "$pyfile" 2>/dev/null \
      && pass "$pyfile passes Python syntax check" \
      || fail "$pyfile has Python syntax errors"
  done
fi

# Bash syntax check
if command -v bash &>/dev/null; then
  for shfile in scripts/*.sh; do
    [ -f "$shfile" ] || continue
    bash -n "$shfile" 2>/dev/null \
      && pass "$shfile passes bash syntax check" \
      || fail "$shfile has bash syntax errors"
  done
fi

echo ""

# ── Security ───────────────────────────────────────────────────────────────────
echo "── Security ──"

# voice-confirm.py specific checks
if [ -f scripts/voice-confirm.py ]; then
  # Uses subprocess with fixed args (not shell=True)
  grep -q "shell=True" scripts/voice-confirm.py \
    && warn "voice-confirm.py uses shell=True (potential injection risk)" \
    || pass "voice-confirm.py does not use shell=True"

  # Caps TTS input length
  grep -q "cmd\[:200\]" scripts/voice-confirm.py \
    && pass "voice-confirm.py caps command length before TTS" \
    || warn "voice-confirm.py may not cap command length for TTS"

  # Has keyboard fallback
  grep -q "keyboard_confirm" scripts/voice-confirm.py \
    && pass "voice-confirm.py has keyboard fallback" \
    || fail "voice-confirm.py missing keyboard fallback"
fi

echo ""

# ── Summary ────────────────────────────────────────────────────────────────────
echo "══════════════════════════════════════════"
echo "Results: ${PASS} passed, ${WARN} warnings, ${FAIL} failed"
echo ""

if [ "$FAIL" -gt 0 ]; then
  echo "Status: NEEDS ATTENTION (fix failures above)"
  exit 1
elif [ "$WARN" -gt 0 ]; then
  echo "Status: GOOD (some optional improvements available)"
  exit 0
else
  echo "Status: EXCELLENT"
  exit 0
fi
