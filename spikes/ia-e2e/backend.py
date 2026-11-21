"""Backend local para la prueba de punta a punta (spikes/ia-e2e): la app real, con dos piezas falsas.

* **El LLM:** ScriptedChat (chat) y ScriptedAnalyst (ingesta). No hay keys reales en este entorno.
* **GitHub:** LocalGitHub sirve los proyectos de toys/ como si fueran repos de una instalación.

Todo lo demás es lo de verdad: rutas, Postgres, Supabase Auth y Storage del stack local, el analizador con
check_evidence, el motor y los costos. Uso, desde la raíz del repo y con `npx supabase start`:

  backend/.venv/bin/python spikes/ia-e2e/backend.py <user_id de la sesión de prueba>
"""

import io
import json
import os
import re
import sys
import tarfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[1] / "backend"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(HERE))
os.chdir(BACKEND)

from local_stack import keys  # noqa: E402

os.environ.update(
    DATABASE_URL="postgresql://postgres:postgres@127.0.0.1:54322/postgres",
    SUPABASE_URL="http://127.0.0.1:54321",
    SUPABASE_SECRET_KEY=keys()["SECRET_KEY"],  # la del stack local, de `npx supabase status`
    ANTHROPIC_API_KEY="sk-ant-local-falsa",  # la "key de Branchpoint": el LLM es el del guion
    BRANCHPOINT_FRONTEND_URL="http://localhost:3000",
    BRANCHPOINT_TEAM_EXTRACT_LIMIT="10",
)
os.environ.pop("BRANCHPOINT_AUTH", None)

import uvicorn  # noqa: E402
from app.agent.loop import Turn  # noqa: E402
from app.api.main import create_app  # noqa: E402
from app.github.client import GitHubApp, GitHubAppConfig, Repo  # noqa: E402

from analyst import ScriptedAnalyst  # noqa: E402

INSTALLATION = 4242
TOYS = sorted(p for p in (HERE / "toys").iterdir() if p.is_dir())
SHA = "e2e0000000000000000000000000000000000000"


class LocalGitHub(GitHubApp):
    """Una instalación con los repos de toys/. Los tarballs se arman desde disco."""

    def __init__(self) -> None:
        super().__init__(GitHubAppConfig("1", "branchpoint-e2e", "Iv1.e2e", "secreto-local", "sin-key"))

    def list_repos(self, installation_id: int) -> list[Repo]:
        return [Repo(100 + i, f"toys/{p.name}", False, "main", INSTALLATION) for i, p in enumerate(TOYS)]

    def list_branches(self, installation_id: int, full_name: str) -> list[str]:
        return ["main"]

    def fetch(self, installation_id: int, full_name: str, ref: str) -> tuple[str, bytes]:
        folder = HERE / "toys" / full_name.split("/", 1)[1]
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            tar.add(folder, arcname=f"toys-{folder.name}-{SHA[:7]}")
        return SHA, buf.getvalue()


def use(name, args, n=1):
    return {"type": "tool_use", "id": f"t{n}-{name}", "name": name, "input": args}


class ScriptedChat:
    """Hace de agente del chat con un guion fijo, usando las tools reales del backend."""

    model = "claude-opus-5-5"

    def complete(self, system, messages, tools):
        if "report_no_endpoints" in [t["name"] for t in tools]:  # la ingesta, no el chat
            return ScriptedAnalyst().complete(system, messages, tools)
        pid = re.search(r"project_id='([^']+)'", system)[1]
        last = messages[-1]
        content = last["content"]
        if isinstance(content, list) and content and content[0].get("type") == "tool_result":
            result = json.loads(content[0]["content"])
            name = next(
                b["name"]
                for m in reversed(messages)
                if m["role"] == "assistant"
                for b in m["content"]
                if b.get("type") == "tool_use"
            )
            if name == "analyze_log":
                if "error" in result:
                    return Turn([{"type": "text", "text": f"No pude leer el log: {result['error']}"}], "end_turn")
                aid = re.findall(r"id ([0-9a-f-]{36})", json.dumps(messages, ensure_ascii=False))[-1]
                return Turn([use("apply_log_traffic", {"project_id": pid, "attachment_id": aid}, 2)], "tool_use")
            if name == "apply_log_traffic":
                text = (
                    f"Listo: la versión v{result['version']} usa el tráfico observado en el log "
                    f"({result['peak_rps']['value']} req/s de pico, {result['peak_rps']['label']})."
                )
                return Turn([{"type": "text", "text": text}], "end_turn")
            return Turn([{"type": "text", "text": json.dumps(result, ensure_ascii=False)[:500]}], "end_turn")
        text = content if isinstance(content, str) else " ".join(b.get("text", "") for b in content)
        logs = re.findall(r"\[Adjunto de log: [^,]+, id ([0-9a-f-]{36})", text)
        if logs:
            return Turn([use("analyze_log", {"project_id": pid, "attachment_id": logs[-1]})], "tool_use")
        if isinstance(content, list) and any(b.get("type") == "image" for b in content):
            n = sum(1 for b in content if b.get("type") == "image")
            reply = (
                f"Recibí {n} imagen(es). Si el panel muestra el pico de requests por segundo, escríbeme el número "
                "con tus palabras para guardarlo; no lo guardo leyéndolo de la imagen."
            )
            return Turn([{"type": "text", "text": reply}], "end_turn")
        reply = (
            "El tráfico de este proyecto es un supuesto. Para respaldar la conclusión, súbeme un log de acceso "
            "(nginx o JSON por línea) o una captura de tus métricas de requests por segundo."
        )
        return Turn([{"type": "text", "text": reply}], "end_turn")


app = create_app(github_app=LocalGitHub())
app.state.llm_factory = lambda key, model=None: ScriptedChat()
app.state.openai_llm_factory = lambda key, model=None: ScriptedChat()

if __name__ == "__main__":
    if len(sys.argv) > 1:  # la instalación de GitHub queda a nombre del usuario de prueba
        app.state.store.save_installation(INSTALLATION, sys.argv[1], "toys")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
