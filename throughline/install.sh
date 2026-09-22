#!/usr/bin/env bash
# Installs GitHub Copilot Throughline as a GitHub Copilot CLI skill by
# copying this repository to ~/.copilot/skills/throughline/ (ARCH §3).
# Nothing more elaborate: no pip install, no network, no build step — the
# Engine is Python 3.11+ stdlib only.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_DIR="${THROUGHLINE_SKILL_HOME:-$HOME/.copilot/skills/throughline}"

echo "GitHub Copilot Throughline installer"
echo "  Source: $SCRIPT_DIR"
echo "  Target: $TARGET_DIR"

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 was not found on PATH. GitHub Copilot Throughline requires Python 3.11+." >&2
  exit 1
fi

PY_VERSION="$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')"
PY_MAJOR="$(python3 -c 'import sys; print(sys.version_info[0])')"
PY_MINOR="$(python3 -c 'import sys; print(sys.version_info[1])')"
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]; }; then
  echo "ERROR: python3 is version $PY_VERSION; GitHub Copilot Throughline requires 3.11+." >&2
  exit 1
fi
echo "  python3: $PY_VERSION (OK)"

mkdir -p "$(dirname "$TARGET_DIR")"
if [ -d "$TARGET_DIR" ]; then
  echo "  Existing install found; updating in place (workspace data is stored separately and is never touched)."
  rm -rf "$TARGET_DIR"
fi
cp -R "$SCRIPT_DIR" "$TARGET_DIR"
chmod +x "$TARGET_DIR/bin/throughline" "$TARGET_DIR/bin/throughline-engine"

echo "Installed. Talk workspace data lives under ~/.copilot/throughline/workspace/"
echo "and is never touched by re-installing or updating this skill."
echo
echo "Try it:"
echo "  \"$TARGET_DIR/bin/throughline\" workspace show"
echo "  (\"bin/throughline-engine\" also works, kept as a backward-compatible alias)"
echo
echo "Then open a GitHub Copilot CLI session and type: throughline"
