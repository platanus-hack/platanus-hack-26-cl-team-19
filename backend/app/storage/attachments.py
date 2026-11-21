"""Adjuntos del chat en Supabase Storage (IA-6, JAJ-115).

El archivo va del navegador a Storage directo, con una URL firmada: el backend nunca lo recibe en una
request. Solo firma, registra el adjunto y lo descarga cuando una tool lo necesita.

Endpoints de la API REST de Storage que usa (verificados contra storage-api v1.96 del stack local):

* ``POST /storage/v1/object/upload/sign/{bucket}/{path}`` → ``{"url": "/object/upload/sign/...?token="}``.
  El navegador sube con ``PUT`` a esa URL, sin auth. Sin ``x-upsert`` no pisa un objeto que ya existe.
* ``GET /storage/v1/object/info/{bucket}/{path}`` → ``size`` y ``content_type`` (404 si no existe).
* ``GET /storage/v1/object/authenticated/{bucket}/{path}``, con ``Range: bytes=0-N`` para no bajar de más.
* ``DELETE /storage/v1/object/{bucket}`` con ``{"prefixes": [paths]}``.

Todas con la secret key en ``apikey`` y ``Authorization``. El bucket ``chat-attachments`` es privado y
sin políticas para ``anon`` ni ``authenticated`` (``supabase/migrations/20261121181000_chat_attachments.sql``).
"""

from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

BUCKET = "chat-attachments"
TIMEOUT_S = 20


class StorageError(Exception):
    """Storage no respondió como se esperaba. El mensaje no trae la key ni la URL firmada."""


class AttachmentStorage:
    """Cliente mínimo de Supabase Storage con la secret key del backend."""

    def __init__(self, supabase_url: str, secret_key: str, bucket: str = BUCKET) -> None:
        self._base = supabase_url.rstrip("/") + "/storage/v1"
        self._key = secret_key
        self.bucket = bucket

    def __repr__(self) -> str:
        return f"AttachmentStorage({self._base!r}, bucket={self.bucket!r})"

    def _url(self, kind: str, path: str) -> str:
        return f"{self._base}/object/{kind}{self.bucket}/{urllib.parse.quote(path)}"

    def _request(
        self, method: str, url: str, body: bytes | None = None, headers: dict[str, str] | None = None
    ) -> tuple[int, dict[str, str], bytes]:
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header("apikey", self._key)
        req.add_header("Authorization", f"Bearer {self._key}")
        for name, value in (headers or {}).items():
            req.add_header(name, value)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:  # la URL sale de SUPABASE_URL
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers or {}), e.read()
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise StorageError(f"Supabase Storage no responde ({type(e).__name__}).") from None

    def signed_upload(self, path: str) -> str:
        """URL absoluta para que el navegador suba el archivo con ``PUT``. Vence a las 2 horas."""
        status, _, body = self._request("POST", self._url("upload/sign/", path))
        if status != 200:
            raise StorageError(f"Storage no firmó la subida (HTTP {status}).")
        return self._base + json.loads(body)["url"]

    def head(self, path: str) -> tuple[int, str] | None:
        """``(bytes, media_type)`` del objeto subido, o ``None`` si no existe."""
        status, _, body = self._request("GET", self._url("info/", path))
        if status in (400, 404):
            return None
        if status != 200:
            raise StorageError(f"Storage no respondió por el archivo (HTTP {status}).")
        info = json.loads(body)
        return int(info["size"]), str(info.get("content_type") or "")

    def download(self, path: str, max_bytes: int) -> bytes:
        """El contenido, hasta ``max_bytes``. ``StorageError`` si el objeto no existe."""
        status, _, body = self._request(
            "GET", self._url("authenticated/", path), headers={"Range": f"bytes=0-{max_bytes - 1}"}
        )
        if status not in (200, 206):
            raise StorageError(f"Storage no entregó el archivo (HTTP {status}).")
        return body[:max_bytes]

    def delete(self, paths: list[str]) -> None:
        if not paths:
            return
        status, _, _ = self._request(
            "DELETE",
            f"{self._base}/object/{self.bucket}",
            json.dumps({"prefixes": paths}).encode(),
            {"Content-Type": "application/json"},
        )
        if status != 200:
            raise StorageError(f"Storage no borró los archivos (HTTP {status}).")


class InMemoryAttachmentStorage:
    """La misma interfaz en memoria, para los tests y para correr sin Supabase. ``put`` hace de navegador."""

    bucket = BUCKET

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self._lock = threading.Lock()

    def signed_upload(self, path: str) -> str:
        return f"memory://{BUCKET}/{urllib.parse.quote(path)}"

    def put(self, path: str, data: bytes, media_type: str) -> None:
        with self._lock:
            self.objects[path] = (data, media_type)

    def head(self, path: str) -> tuple[int, str] | None:
        obj = self.objects.get(path)
        return (len(obj[0]), obj[1]) if obj else None

    def download(self, path: str, max_bytes: int) -> bytes:
        obj = self.objects.get(path)
        if obj is None:
            raise StorageError("No existe el archivo.")
        return obj[0][:max_bytes]

    def delete(self, paths: list[str]) -> None:
        with self._lock:
            for path in paths:
                self.objects.pop(path, None)


def attachment_storage_from_env() -> Any:
    """``AttachmentStorage`` con ``SUPABASE_URL`` y ``SUPABASE_SECRET_KEY``; ``None`` sin ellas (503)."""
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_SECRET_KEY", "").strip()
    return AttachmentStorage(url, key) if url and key else None
