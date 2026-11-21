"""Catálogo de números con procedencia: tiempos (JAJ-8, JAJ-43, JAJ-46), planes y precios (JAJ-11).

Es una copia de ``spikes/jaj-45-numeros/catalog.json``, la fuente que usa ``build_model.py``. Un
test verifica que las dos copias sean iguales, así que se edita allá y se copia acá.
"""

from __future__ import annotations

import copy
import json
from functools import cache
from pathlib import Path
from typing import Any

CATALOG_PATH = Path(__file__).parent / "catalog.json"


@cache
def _read() -> dict[str, Any]:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def load_catalog() -> dict[str, Any]:
    """El catálogo como dict (una copia nueva cada vez, para que nadie modifique el compartido)."""
    return copy.deepcopy(_read())
