"""Spike JAJ-53: descarga un repo de GitHub con un token y corre el extractor de JAJ-7.

Uso:
    GITHUB_TOKEN=... python fetch_repo.py <owner>/<repo> [--ref main] [-o salida.json] [--keep DIR]

Sirve igual con un token de instalación de GitHub App, un user access token o un token de
OAuth App: el endpoint de tarball es el mismo. Usa solo la librería estándar.

Pasos que mide:
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


def download_tarball(full_name: str, ref: str | None, token: str) -> bytes:
    url = f"{API}/repos/{full_name}/tarball" + (f"/{ref}" if ref else "")
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "branchpoint-spike",
    })
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

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise SystemExit("Falta GITHUB_TOKEN")

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
