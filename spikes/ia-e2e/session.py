"""Crea (o reutiliza) un usuario de prueba en el Supabase local y deja su sesión lista para el navegador.

  backend/.venv/bin/python spikes/ia-e2e/session.py

Escribe ``.e2e/`` (no se versiona): la contraseña generada, la sesión y ``inject.js``, que se pega en la consola
del navegador en http://localhost:3000 para quedar con sesión. Imprime el id del usuario, que va como argumento
de ``backend.py``. Solo para el stack local: lee sus keys con ``npx supabase status``.
"""

import json
import secrets
import time
import urllib.error
import urllib.request
from pathlib import Path

from local_stack import keys

URL = "http://127.0.0.1:54321"
SECRET = keys()["SECRET_KEY"]  # del stack local, de `npx supabase status`
PUBLISHABLE = keys()["PUBLISHABLE_KEY"]
OUT = Path(__file__).parent / ".e2e"


def call(path: str, body: dict | None, key: str, method: str = "POST") -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{URL}{path}", data=data, method=method)
    req.add_header("apikey", key)
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


def main() -> None:
    OUT.mkdir(exist_ok=True)
    cred_file = OUT / "user.json"
    if not cred_file.exists():
        cred_file.write_text(json.dumps({"email": "e2e@branchpoint.test", "password": secrets.token_urlsafe(18)}))
    cred = json.loads(cred_file.read_text())
    call("/auth/v1/admin/users", {**cred, "email_confirm": True}, SECRET)  # ya existe: responde 422 y sigue
    status, session = call("/auth/v1/token?grant_type=password", cred, PUBLISHABLE)
    if status == 400:  # el usuario ya existía con otra contraseña (de una corrida anterior): se la cambia
        _, users = call("/auth/v1/admin/users?per_page=1000", None, SECRET, "GET")
        user = next(u for u in users["users"] if u["email"] == cred["email"])
        call(f"/auth/v1/admin/users/{user['id']}", {"password": cred["password"]}, SECRET, "PUT")
        status, session = call("/auth/v1/token?grant_type=password", cred, PUBLISHABLE)
    if status != 200:
        raise SystemExit(f"No se pudo iniciar sesión ({status}): {session}")
    session.setdefault("expires_at", int(time.time()) + session["expires_in"])
    uid = session["user"]["id"]
    (OUT / "inject.js").write_text(
        f"localStorage.setItem('sb-127-auth-token', {json.dumps(json.dumps(session))});"
        f"localStorage.setItem('branchpoint:onboarding:{uid}', 'done'); location.href = '/projects';"
    )
    print(uid)


if __name__ == "__main__":
    main()
