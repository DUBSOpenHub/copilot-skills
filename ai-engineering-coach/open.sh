#!/usr/bin/env bash
set -euo pipefail

readonly REPO="${HOME}/copilot-workspace/AI-Engineering-Coach"
readonly COPILOT_APP="/Applications/GitHub Copilot.app"
readonly APP_JS="${REPO}/dist/webview/app.js"
readonly CANVAS_HOST="${REPO}/dist/canvas-host.cjs"

fail() {
  printf 'AI Engineering Coach: %s\n' "$1" >&2
  exit 1
}

check_prerequisites() {
  [[ -d "${REPO}/.git" ]] ||
    fail "repository missing at ${REPO}"
  [[ -f "${REPO}/package.json" ]] ||
    fail "package.json missing at ${REPO}"
  [[ -d "${COPILOT_APP}" ]] ||
    fail "GitHub Copilot app is not installed in /Applications"
  command -v node >/dev/null 2>&1 ||
    fail "Node.js is required"
  command -v npm >/dev/null 2>&1 ||
    fail "npm is required"
}

is_built() {
  [[ -f "${APP_JS}" && -f "${CANVAS_HOST}" ]]
}

build() {
  npm --prefix "${REPO}" ci --no-audit --no-fund
  npm --prefix "${REPO}" run build
}

check_prerequisites

case "${1:-}" in
  --check)
    is_built || fail "build artifacts are missing; run the skill to build them"
    printf 'AI Engineering Coach is ready at %s\n' "${REPO}"
    exit 0
    ;;
  --update)
    [[ -z "$(git -C "${REPO}" status --porcelain)" ]] ||
      fail "update refused because the repository has local changes"
    git -C "${REPO}" pull --ff-only
    build
    ;;
  "")
    if ! is_built; then
      build
    fi
    ;;
  *)
    fail "usage: open.sh [--check|--update]"
    ;;
esac

open -a "GitHub Copilot" "${REPO}"
printf 'AI Engineering Coach opened in the GitHub Copilot app.\n'
