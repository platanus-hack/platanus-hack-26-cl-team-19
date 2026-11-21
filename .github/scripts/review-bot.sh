#!/usr/bin/env bash
# Corre el bot reviewer en tu laptop (JAJ-63). La key de Anthropic se lee del llavero de macOS, así no
# queda en el repo, en un archivo ni en el historial de la terminal. Ver docs/bot-reviewer.md.
#
#   .github/scripts/review-bot.sh --watch      # revisa cada PR abierta con un push nuevo, cada 2 minutos
#   .github/scripts/review-bot.sh --pr 34      # revisa una PR
#   .github/scripts/review-bot.sh --dry-run --pr 34   # muestra el prompt, sin gastar tokens
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VENV="${BRANCHPOINT_REVIEW_VENV:-$HOME/.cache/branchpoint-review-bot/venv}"
KEYCHAIN_SERVICE="branchpoint-anthropic-api-key"

if [[ ! -x "$VENV/bin/python" ]]; then
  echo "Creando el entorno del bot en $VENV (solo la primera vez)..." >&2
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install -q "anthropic==2.12.0"
fi

if [[ -z "${ANTHROPIC_API_KEY:-}" ]] && command -v security >/dev/null; then
  ANTHROPIC_API_KEY="$(security find-generic-password -s "$KEYCHAIN_SERVICE" -w 2>/dev/null || true)"
fi
if [[ -z "${ANTHROPIC_API_KEY:-}" && " $* " != *" --dry-run "* ]]; then
  echo "No encontré la key. Guárdala una vez en el llavero (te la pide sin mostrarla):" >&2
  echo "  security add-generic-password -a \"\$USER\" -s $KEYCHAIN_SERVICE -w" >&2
  exit 1
fi
export ANTHROPIC_API_KEY

if [[ -z "${LINEAR_API_KEY:-}" ]] && command -v security >/dev/null; then
  LINEAR_API_KEY="$(security find-generic-password -s branchpoint-linear-api-key -w 2>/dev/null || true)"
  export LINEAR_API_KEY
fi

cd "$ROOT"
exec "$VENV/bin/python" .github/scripts/pr_review.py "$@"
