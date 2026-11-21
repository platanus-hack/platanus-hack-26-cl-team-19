"""Modelos de ejemplo (``branchpoint.model/v1``) para abrir el editor sin ingerir un repo.

Son la salida de ``build_model.py`` (JAJ-45, ``spikes/jaj-45-numeros/results``). El id de cada uno
es el nombre del archivo sin ``.model.json``.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

SAMPLES_DIR = Path(__file__).parent
SUFFIX = ".model.json"


def sample_ids() -> list[str]:
    return sorted(p.name.removesuffix(SUFFIX) for p in SAMPLES_DIR.glob(f"*{SUFFIX}"))


@cache
def _read(sample_id: str) -> str:
    return (SAMPLES_DIR / f"{sample_id}{SUFFIX}").read_text(encoding="utf-8")


def load_sample(sample_id: str) -> dict[str, Any] | None:
    """El modelo de ejemplo como dict (una copia nueva cada vez), o ``None`` si no existe."""
    if sample_id not in sample_ids():
        return None
    return json.loads(_read(sample_id))
