"""Las keys del stack local de Supabase, leídas de `npx supabase status` (no se escriben en el repo)."""

from __future__ import annotations

import functools
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


@functools.cache
def keys() -> dict[str, str]:
    """``{"SECRET_KEY", "PUBLISHABLE_KEY", "API_URL", "DB_URL"}`` del stack levantado con `npx supabase start`."""
    out = subprocess.run(
        ["npx", "-y", "supabase@3.2.0", "status", "-o", "json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    ).stdout
    data = json.loads(out[out.index("{") :])
    missing = [k for k in ("SECRET_KEY", "PUBLISHABLE_KEY", "API_URL") if not data.get(k)]
    if missing:
        raise SystemExit(f"`npx supabase status` no trae {missing}: ¿está levantado el stack completo?")
    return data
