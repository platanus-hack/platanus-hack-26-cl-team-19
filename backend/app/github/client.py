"""Cliente de la GitHub App de Branchpoint (JAJ-57). El diseño está en spikes/jaj-53-acceso-github.

* La app se autentica con un JWT RS256 firmado con su private key (vale 10 minutos como máximo).
* Con ese JWT pide un **token de instalación**: 1 hora, acotado a un repo y a ``contents: read``.
  No se guarda: se pide en cada llamada y nunca sale en logs, errores ni respuestas de la API.
* El código se baja como tarball (``GET /repos/{owner}/{repo}/tarball/{sha}``).
* Para ligar una instalación a un usuario, el ``code`` de OAuth que trae el callback se canjea por
  un token de usuario y se confirma con ``GET /user/installations`` que esa persona la ve.

Configuración (``backend/.env``): ``GITHUB_APP_ID``, ``GITHUB_APP_SLUG``, ``GITHUB_APP_CLIENT_ID``,
``GITHUB_APP_CLIENT_SECRET`` y la private key en ``GITHUB_APP_PRIVATE_KEY_PATH`` (un archivo fuera del
repo) o en ``GITHUB_APP_PRIVATE_KEY`` (su contenido, para el host de producción).
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jwt

API = "https://api.github.com"
# GitHub no documenta un tope. El tarball se lee entero en memoria y Render free tiene 512 MB (JAJ-84),
# así que el tope por defecto es 80 MB comprimido. BRANCHPOINT_MAX_TARBALL_MB lo cambia.
MAX_TARBALL_BYTES = int(float(os.environ.get("BRANCHPOINT_MAX_TARBALL_MB", "80")) * 1024 * 1024)


class GitHubError(Exception):
    """GitHub respondió con error. ``message`` está en español y se puede mostrar tal cual."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass(frozen=True)
class Repo:
    id: int
    full_name: str
    private: bool
    default_branch: str
    installation_id: int


@dataclass(frozen=True)
class GitHubAppConfig:
    app_id: str
    slug: str
    client_id: str
    client_secret: str
    private_key: str

    @classmethod
    def from_env(cls) -> GitHubAppConfig | None:
        """``None`` si falta algo: las rutas de GitHub responden 503 en vez de fallar al arrancar."""
        env = os.environ
        key = env.get("GITHUB_APP_PRIVATE_KEY")
        if not key and (path := env.get("GITHUB_APP_PRIVATE_KEY_PATH")):
            p = Path(path).expanduser()
            key = p.read_text() if p.is_file() else None
        values = [env.get(k) for k in ("GITHUB_APP_ID", "GITHUB_APP_SLUG", "GITHUB_APP_CLIENT_ID")]
        secret = env.get("GITHUB_APP_CLIENT_SECRET")
        if not (all(values) and secret and key):
            return None
        app_id, slug, client_id = values
        return cls(app_id, slug, client_id, secret, key)  # type: ignore[arg-type]


class GitHubApp:
    def __init__(self, config: GitHubAppConfig) -> None:
        self.config = config

    # ---------- autenticación ----------

    def install_url(self, state: str) -> str:
        """Donde el usuario instala la app y elige los repos. GitHub vuelve a la Callback URL con ``state``."""
        return f"https://github.com/apps/{self.config.slug}/installations/new?" + urllib.parse.urlencode(
            {"state": state}
        )

    def authorize_url(self, state: str, redirect_uri: str | None = None) -> str:
        """OAuth web de la app: después de instalarla (en otra pestaña) o si ya estaba instalada. Vuelve
        con ``code`` y sin ``installation_id``. ``redirect_uri`` elige a cuál de las Callback URL vuelve
        (tiene que coincidir exacto con una): así producción y local usan la misma app (JAJ-84). Sin él,
        GitHub usa la primera de la lista."""
        params = {"client_id": self.config.client_id, "state": state}
        if redirect_uri:
            params["redirect_uri"] = redirect_uri
        return "https://github.com/login/oauth/authorize?" + urllib.parse.urlencode(params)

    def _app_jwt(self) -> str:
        now = int(time.time())
        # iat 60 s atrás por desfase de reloj; GitHub acepta como máximo 10 minutos de vida
        claims = {"iat": now - 60, "exp": now + 9 * 60, "iss": self.config.app_id}
        return jwt.encode(claims, self.config.private_key, algorithm="RS256")

    def installation_token(self, installation_id: int, repo_name: str | None = None) -> str:
        """Token de instalación de 1 hora con ``contents: read``. Con ``repo_name`` (sin el owner), solo
        sirve para ese repo: si la app no está instalada ahí, GitHub responde 422."""
        body: dict[str, Any] = {"permissions": {"contents": "read"}}
        if repo_name:
            body["repositories"] = [repo_name]
        data = self._request(
            "POST", f"/app/installations/{installation_id}/access_tokens", self._app_jwt(), body, what="token"
        )
        return data["token"]

    def user_installations(self, code: str, redirect_uri: str | None = None) -> dict[int, str]:
        """Canjea el ``code`` del callback y devuelve las instalaciones de esta app que ve ese usuario de
        GitHub (id → cuenta donde está instalada). ``GitHubError`` si el code no sirve."""
        req = urllib.request.Request(
            "https://github.com/login/oauth/access_token",
            data=urllib.parse.urlencode(
                {
                    "client_id": self.config.client_id,
                    "client_secret": self.config.client_secret,
                    "code": code,
                    # el mismo redirect_uri del authorize; si no coincide, GitHub responde redirect_uri_mismatch
                    **({"redirect_uri": redirect_uri} if redirect_uri else {}),
                }
            ).encode(),
            headers={"Accept": "application/json", "User-Agent": "branchpoint"},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                granted = json.load(resp)
        except urllib.error.URLError:
            raise GitHubError(502, "GitHub no respondió al verificar la instalación. Intenta de nuevo.") from None
        user_token = granted.get("access_token")
        if not user_token:
            raise GitHubError(401, "GitHub rechazó la autorización (el código venció o ya se usó). Vuelve a conectar.")
        found: dict[int, str] = {}
        page = 1
        while True:  # un usuario puede ver varias instalaciones (su cuenta y sus orgs)
            data = self._request("GET", f"/user/installations?per_page=100&page={page}", user_token, what="user")
            batch = data.get("installations", [])
            found |= {inst["id"]: (inst.get("account") or {}).get("login") or "" for inst in batch}
            if len(batch) < 100:
                return found
            page += 1

    # ---------- repos ----------

    def list_repos(self, installation_id: int) -> list[Repo]:
        token = self.installation_token(installation_id)
        repos: list[Repo] = []
        page = 1
        while True:
            data = self._request("GET", f"/installation/repositories?per_page=100&page={page}", token, what="repos")
            batch = data.get("repositories", [])
            repos += [
                Repo(r["id"], r["full_name"], r["private"], r.get("default_branch") or "main", installation_id)
                for r in batch
            ]
            if len(batch) < 100:
                return repos
            page += 1

    def list_branches(self, installation_id: int, full_name: str) -> list[str]:
        token = self.installation_token(installation_id, full_name.split("/", 1)[1])
        data = self._request("GET", f"/repos/{full_name}/branches?per_page=100", token, what="branches")
        return [b["name"] for b in data]

    def fetch(self, installation_id: int, full_name: str, ref: str) -> tuple[str, bytes]:
        """El SHA del commit de ``ref`` y su tarball. Pide el SHA primero para analizar y guardar
        exactamente el mismo commit aunque la rama avance durante la descarga."""
        token = self.installation_token(installation_id, full_name.split("/", 1)[1])
        ref_q = urllib.parse.quote(ref, safe="")
        sha = self._request(
            "GET", f"/repos/{full_name}/commits/{ref_q}", token, accept="application/vnd.github.sha", what="ref"
        )
        data = self._request("GET", f"/repos/{full_name}/tarball/{sha}", token, what="tarball", timeout=60)
        return sha, data

    # ---------- HTTP ----------

    def _request(
        self,
        method: str,
        path: str,
        token: str,
        body: dict[str, Any] | None = None,
        *,
        what: str,
        accept: str = "application/vnd.github+json",
        timeout: float = 20,
    ) -> Any:
        req = urllib.request.Request(
            API + path,
            data=json.dumps(body).encode() if body is not None else None,
            method=method,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": accept,
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "branchpoint",
                **({"Content-Type": "application/json"} if body is not None else {}),
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # sigue el 302 del tarball a codeload
                if what == "tarball":
                    data = resp.read(MAX_TARBALL_BYTES + 1)
                    if len(data) > MAX_TARBALL_BYTES:
                        mb = MAX_TARBALL_BYTES // (1024 * 1024)
                        raise GitHubError(413, f"El repo pesa más de {mb} MB comprimido y no se puede analizar.")
                    return data
                raw = resp.read()
        except urllib.error.HTTPError as e:
            raise GitHubError(e.code, _message(e.code, what)) from None  # sin el cuerpo: puede traer datos
        except (urllib.error.URLError, TimeoutError):
            raise GitHubError(502, "GitHub no respondió a tiempo. Intenta de nuevo.") from None
        return raw.decode().strip() if accept == "application/vnd.github.sha" else json.loads(raw)


def _message(status: int, what: str) -> str:
    """Los errores de GitHub en español. Las respuestas que se observaron están en el README de JAJ-53."""
    if what == "token":
        if status == 422:
            return "La GitHub App no está instalada en ese repo. Agrégalo a la instalación y vuelve a intentar."
        if status == 404:
            return "La instalación de la GitHub App ya no existe: la desinstalaron o se revocó el acceso."
        if status == 401:
            return "GitHub rechazó la credencial de la app. Revisa GITHUB_APP_ID y la private key del backend."
    if what in ("ref", "tarball", "branches") and status == 404:
        return "GitHub no encontró ese repo o esa rama, o la app ya no tiene acceso."
    if status in (403, 429):
        return "GitHub limitó las solicitudes (rate limit). Espera un minuto y vuelve a intentar."
    return f"GitHub respondió {status}. Intenta de nuevo."
