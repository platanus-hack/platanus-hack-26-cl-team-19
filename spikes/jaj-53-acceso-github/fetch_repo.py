"""Spike JAJ-53: descarga un repo de GitHub con un token y corre el extractor de JAJ-7.

Uso:
    GITHUB_TOKEN=... python fetch_repo.py <owner>/<repo> [--ref main] [-o salida.json] [--keep DIR]

Modo GitHub App (JAJ-65): sin GITHUB_TOKEN, firma un JWT RS256 con la private key de la app y
pide un token de instalación acotado a ese repo y a `contents: read`.
    GITHUB_APP_ID=... GITHUB_APP_PRIVATE_KEY_PATH=~/.config/branchpoint/github-app.pem \
    GITHUB_APP_INSTALLATION_ID=... python fetch_repo.py <owner>/<repo>
La private key también se puede pasar con su contenido en GITHUB_APP_PRIVATE_KEY. Nunca va en el
repo. Este modo necesita PyJWT con `cryptography` (`pyjwt[crypto]`, ya está en backend/); el modo
con GITHUB_TOKEN usa solo la librería estándar.

Pasos que mide:
0. Solo en modo app: JWT y `POST /app/installations/{id}/access_tokens`.
1. Descarga del tarball (`GET /repos/{owner}/{repo}/tarball/{ref}`).
2. Extracción segura a un directorio temporal (filtro `data` de tarfile: sin rutas fuera del
   directorio, sin symlinks absolutos ni archivos de dispositivo).
3. Extractor AST de JAJ-7, sin importar ni ejecutar el código.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "jaj-7-ingestion"))

import extract  # noqa: E402  (spikes/jaj-7-ingestion/extract.py)

API = "https://api.github.com"
MAX_BYTES = 200 * 1024 * 1024  # tope de descarga para que un repo gigante no llene el disco


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "branchpoint-spike",
    }


def _read_private_key() -> str:
    if key := os.environ.get("GITHUB_APP_PRIVATE_KEY"):
        return key
    path = os.environ.get("GITHUB_APP_PRIVATE_KEY_PATH")
    if not path:
        raise SystemExit("Falta GITHUB_APP_PRIVATE_KEY_PATH (o GITHUB_APP_PRIVATE_KEY)")
    return Path(path).expanduser().read_text()


def app_jwt(app_id: str, private_key: str) -> str:
    import jwt  # PyJWT; solo se necesita en modo app

    now = int(time.time())
    # iat 60 s atrás por desfase de reloj; GitHub acepta como máximo 10 min de vida.
    return jwt.encode({"iat": now - 60, "exp": now + 9 * 60, "iss": app_id}, private_key, algorithm="RS256")


def installation_token(full_name: str, app_id: str, installation_id: str, private_key: str) -> dict:
    """Pide un token de instalación (1 h) acotado a un solo repo y a `contents: read`."""
    body = json.dumps({"repositories": [full_name.split("/", 1)[1]], "permissions": {"contents": "read"}})
    req = urllib.request.Request(
        f"{API}/app/installations/{installation_id}/access_tokens",
        data=body.encode(),
        method="POST",
        headers=_headers(app_jwt(app_id, private_key)) | {"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        raise SystemExit(f"GitHub respondió {e.code} al pedir el token de instalación: {detail}") from None


def download_tarball(full_name: str, ref: str | None, token: str) -> bytes:
    url = f"{API}/repos/{full_name}/tarball" + (f"/{ref}" if ref else "")
    req = urllib.request.Request(url, headers=_headers(token))
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:  # sigue el 302 a codeload
            data = resp.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as e:
        # 404 también es lo que responde GitHub cuando el token no tiene acceso a un repo privado.
        raise SystemExit(f"GitHub respondió {e.code} para {full_name}: {e.reason}") from None
    if len(data) > MAX_BYTES:
        raise SystemExit(f"El tarball supera {MAX_BYTES // (1024 * 1024)} MB")
    return data


def safe_extract(data: bytes, dest: Path) -> Path:
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        tar.extractall(dest, filter="data")
    # El tarball trae una carpeta raíz `<owner>-<repo>-<sha>/`.
    roots = [p for p in dest.iterdir() if p.is_dir()]
    return roots[0] if len(roots) == 1 else dest


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("repo", help="owner/nombre")
    ap.add_argument("--ref", help="rama, tag o sha (por defecto, la rama por defecto)")
    ap.add_argument("-o", "--out", type=Path, help="dónde guardar el grafo extraído")
    ap.add_argument("--keep", type=Path, help="extraer aquí en vez de un directorio temporal")
    args = ap.parse_args()

    t_start = time.perf_counter()
    token = os.environ.get("GITHUB_TOKEN")
    mode = "token"
    if not token:
        app_id = os.environ.get("GITHUB_APP_ID")
        installation_id = os.environ.get("GITHUB_APP_INSTALLATION_ID")
        if not (app_id and installation_id):
            raise SystemExit("Falta GITHUB_TOKEN, o GITHUB_APP_ID y GITHUB_APP_INSTALLATION_ID para el modo app")
        mode = "github_app"
        granted = installation_token(args.repo, app_id, installation_id, _read_private_key())
        token = granted["token"]  # nunca se imprime

    t0 = time.perf_counter()
    data = download_tarball(args.repo, args.ref, token)
    t1 = time.perf_counter()

    with tempfile.TemporaryDirectory(prefix="branchpoint-") as tmp:
        dest = args.keep or Path(tmp)
        dest.mkdir(parents=True, exist_ok=True)
        root = safe_extract(data, dest)
        t2 = time.perf_counter()
        py_files = sum(1 for _ in root.rglob("*.py"))
        graph = extract.run(root.resolve())
        t3 = time.perf_counter()

    endpoints = graph.get("endpoints", [])
    summary = {
        "mode": mode,
        **({"installation_token_s": round(t0 - t_start, 2), "token_permissions": granted.get("permissions"),
            "token_expires_at": granted.get("expires_at")} if mode == "github_app" else {}),
        "tarball_mb": round(len(data) / (1024 * 1024), 2),
        "commit_dir": root.name,
        "py_files": py_files,
        "endpoints": len(endpoints),
        "download_s": round(t1 - t0, 2),
        "extract_tar_s": round(t2 - t1, 2),
        "ast_s": round(t3 - t2, 2),
        "total_s": round(t3 - t0, 2),
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if args.out:
        args.out.write_text(json.dumps(graph, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
