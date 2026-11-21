"""Sesiones de Supabase en la API (JAJ-78): quién llama y qué proyectos puede ver.

El frontend inicia sesión con Supabase Auth (JAJ-77) y manda su token de acceso en cada request:
``Authorization: Bearer <access_token>``. La API lo valida acá, sin llamar a Supabase en cada
request:

* **Firma.** Con las claves públicas del proyecto (JWKS, en ``{SUPABASE_URL}/auth/v1/.well-known/jwks.json``),
  que se bajan una vez y se guardan en memoria. Si el proyecto todavía firma con el secreto
  compartido (HS256, el esquema antiguo de Supabase), se valida con ``SUPABASE_JWT_SECRET``.
* **Claims.** ``exp`` (no vencido), ``aud = authenticated`` (un usuario con sesión, no la key anónima)
  e ``iss = {SUPABASE_URL}/auth/v1`` (emitido por nuestro proyecto).
* **Usuario.** ``sub`` es el id de ``auth.users``: el ``owner_id`` de los proyectos.

Configuración (``backend/.env``):

* ``SUPABASE_URL``: con ella, el login es obligatorio en las rutas de proyectos.
* ``SUPABASE_JWT_SECRET``: solo para proyectos con el secreto compartido.
* ``BRANCHPOINT_AUTH=off``: sin login, como antes de JAJ-78 (los proyectos quedan sin dueño). Sirve
  para usar el editor en local mientras no tenga login (JAJ-77). No se usa en producción.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import jwt
from fastapi import Request

from app.api.errors import AUTH_UNAVAILABLE, UNAUTHORIZED, ApiError

AUDIENCE = "authenticated"
JWKS_TTL_S = 600  # Supabase rota las claves con aviso; 10 minutos alcanza para tomar una nueva
_ASYMMETRIC = ["RS256", "ES256", "EdDSA"]


@dataclass(frozen=True)
class User:
    id: str  # auth.users.id (claim sub)
    email: str | None = None


class AuthError(Exception):
    """El token no sirve. ``message`` va tal cual al usuario."""


class SupabaseAuth:
    """Valida tokens de acceso de un proyecto de Supabase.

    ``fetch_jwks`` se puede reemplazar en tests; por defecto baja el JWKS por HTTP.
    """

    def __init__(
        self,
        supabase_url: str,
        jwt_secret: str | None = None,
        fetch_jwks: Callable[[str], dict[str, Any]] | None = None,
        leeway_s: int = 30,
    ) -> None:
        base = supabase_url.rstrip("/")
        self.issuer = f"{base}/auth/v1"
        self.jwks_url = f"{self.issuer}/.well-known/jwks.json"
        self._secret = jwt_secret
        self._fetch = fetch_jwks or _fetch_json
        self._leeway = leeway_s
        self._keys: dict[str, jwt.PyJWK] = {}
        self._fetched_at = 0.0
        self._lock = threading.Lock()

    def verify(self, token: str) -> User:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError:
            raise AuthError("El token de sesión no es un JWT válido. Vuelve a iniciar sesión.") from None
        alg = header.get("alg")
        if alg == "HS256":
            if not self._secret:
                raise AuthError("El token está firmado con el secreto compartido y la API no lo tiene configurado.")
            key: Any = self._secret
            algorithms = ["HS256"]
        elif alg in _ASYMMETRIC:
            key = self._key(header.get("kid")).key
            algorithms = [alg]
        else:
            raise AuthError(f"El token usa un algoritmo que la API no acepta ({alg}).")
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=algorithms,
                audience=AUDIENCE,
                issuer=self.issuer,
                leeway=self._leeway,
                options={"require": ["exp", "sub", "aud", "iss"]},
            )
        except jwt.ExpiredSignatureError:
            raise AuthError("La sesión venció. Vuelve a iniciar sesión.") from None
        except jwt.InvalidAudienceError:
            raise AuthError("El token no es de un usuario con sesión (aud debe ser 'authenticated').") from None
        except jwt.InvalidIssuerError:
            raise AuthError("El token es de otro proyecto de Supabase.") from None
        except jwt.PyJWTError:
            raise AuthError("El token de sesión no es válido. Vuelve a iniciar sesión.") from None
        try:
            user_id = str(uuid.UUID(str(claims["sub"])))  # auth.users.id es uuid
        except ValueError:
            raise AuthError("El token no identifica a un usuario de Supabase (sub no es un uuid).") from None
        return User(id=user_id, email=claims.get("email"))

    def _key(self, kid: str | None) -> jwt.PyJWK:
        """La clave pública con ese ``kid``. Si no está, vuelve a bajar el JWKS (Supabase rotó las claves)."""
        with self._lock:
            stale = time.monotonic() - self._fetched_at > JWKS_TTL_S
            if kid not in self._keys or stale:
                self._refresh()
            key = self._keys.get(kid)
        if key is None:
            raise AuthError("El token está firmado con una clave que el proyecto no publica.")
        return key

    def _refresh(self) -> None:
        try:
            data = self._fetch(self.jwks_url)
        except Exception as e:  # red, DNS, JSON roto
            raise ApiError(
                503, AUTH_UNAVAILABLE, "No se pudo validar la sesión: Supabase Auth no responde. Intenta de nuevo."
            ) from e
        keys = {}
        for jwk in data.get("keys", []):
            try:
                keys[jwk.get("kid")] = jwt.PyJWK(jwk)
            except jwt.PyJWTError:
                continue  # una clave de un tipo que no usamos no invalida las demás
        self._keys, self._fetched_at = keys, time.monotonic()


def _fetch_json(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=5) as r:  # la URL sale de nuestro SUPABASE_URL
        return json.load(r)


def auth_from_env() -> SupabaseAuth | None:
    """``None`` = sin login (``BRANCHPOINT_AUTH=off`` o sin ``SUPABASE_URL``)."""
    if os.environ.get("BRANCHPOINT_AUTH", "").strip().lower() == "off":
        return None
    url = os.environ.get("SUPABASE_URL")
    if not url:
        return None
    return SupabaseAuth(url, jwt_secret=os.environ.get("SUPABASE_JWT_SECRET") or None)


def current_user(request: Request) -> User | None:
    """Dependencia de las rutas privadas. ``None`` si la API corre sin login; si no, el usuario del token
    o 401."""
    auth: SupabaseAuth | None = request.app.state.auth
    if auth is None:
        return None
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise ApiError(401, UNAUTHORIZED, "Inicia sesión para ver tus proyectos (falta el token de sesión).")
    try:
        return auth.verify(token.strip())
    except AuthError as e:
        raise ApiError(401, UNAUTHORIZED, str(e)) from None


def owner_of(user: User | None) -> str | None:
    """El ``owner_id`` de los proyectos: el usuario, o ``None`` sin login."""
    return user.id if user is not None else None
