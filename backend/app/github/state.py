"""El ``state`` que viaja a GitHub y vuelve en el callback (JAJ-57).

El callback es una redirección del navegador desde GitHub, así que no trae el token de sesión de
Supabase. Por eso, antes de mandar al usuario a instalar la app, la API firma con HMAC quién es y
hasta cuándo vale. Al volver, solo se acepta un ``state`` firmado por nosotros y vigente: así nadie
puede ligar una instalación a la cuenta de otro mandándole un link.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

STATE_TTL_S = 15 * 60  # lo que puede tardar alguien en elegir los repos en GitHub


class InvalidState(Exception):
    pass


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign_state(secret: str, user_id: str | None, now: float | None = None) -> str:
    payload = _b64(json.dumps({"u": user_id, "exp": int((now or time.time()) + STATE_TTL_S)}).encode())
    sig = _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def verify_state(secret: str, state: str, now: float | None = None) -> str | None:
    """El ``user_id`` que firmó el state (``None`` = sin login). ``InvalidState`` si no es nuestro o venció."""
    payload, _, sig = state.partition(".")
    expected = _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
    if not sig or not hmac.compare_digest(sig, expected):
        raise InvalidState("El enlace de conexión no es válido. Vuelve a conectar desde Branchpoint.")
    data = json.loads(_unb64(payload))
    if data.get("exp", 0) < (now or time.time()):
        raise InvalidState("El enlace de conexión venció. Vuelve a conectar desde Branchpoint.")
    return data.get("u")
