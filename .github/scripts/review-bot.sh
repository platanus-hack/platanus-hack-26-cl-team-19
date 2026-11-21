#!/usr/bin/env bash
# Corre el bot reviewer en tu laptop (JAJ-63). Se autentica con tu sesión de la CLI `ant`
# (`ant auth login`, sin key), o con ANTHROPIC_API_KEY si la tienes en el entorno. Ver docs/bot-reviewer.md.
#
#   .github/scripts/review-bot.sh --watch             # revisa cada PR abierta con un push nuevo, cada 2 minutos
#   .github/scripts/review-bot.sh --pr 34             # revisa una PR
#   .github/scripts/review-bot.sh --dry-run --pr 34   # muestra el prompt, sin gastar tokens
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VENV="${BRANCHPOINT_REVIEW_VENV:-$HOME/.cache/branchpoint-review-bot/venv}"

ANTHROPIC_SDK="2.12.0" # la misma versión que instala .github/workflows/pr-review.yml
if ! "$VENV/bin/python" -c "import anthropic, sys; sys.exit(anthropic.__version__ != '$ANTHROPIC_SDK')" 2>/dev/null; then
  echo "Preparando el entorno del bot en $VENV (anthropic $ANTHROPIC_SDK)..." >&2
  [[ -x "$VENV/bin/python" ]] || python3 -m venv "$VENV"
  "$VENV/bin/pip" install -q "anthropic==$ANTHROPIC_SDK"
fi

if [[ -z "${ANTHROPIC_API_KEY:-}" && -z "${ANTHROPIC_AUTH_TOKEN:-}" && " $* " != *" --dry-run "* ]]; then
  if ! command -v ant >/dev/null; then
    echo "Falta la CLI de Anthropic. Instálala e inicia sesión una vez (se abre el navegador):" >&2
    echo "  brew install anthropics/tap/ant" >&2
    echo "  ant auth login" >&2
    exit 1
  fi
fi

if [[ -z "${LINEAR_API_KEY:-}" ]] && command -v security >/dev/null; then
  LINEAR_API_KEY="$(security find-generic-password -s branchpoint-linear-api-key -w 2>/dev/null || true)"
  export LINEAR_API_KEY
fi

cd "$ROOT"
exec "$VENV/bin/python" .github/scripts/pr_review.py "$@"
