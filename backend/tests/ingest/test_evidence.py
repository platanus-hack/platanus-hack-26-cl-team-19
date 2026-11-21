"""IA-4 (JAJ-120): evidencia verificada contra el repo, tope de tokens, progreso y errores del proveedor."""

from __future__ import annotations

import json
import os

import anthropic
import httpx
import pytest
from pydantic import ValidationError

from app.agent.loop import Turn, with_cache_breakpoint
from app.github.ingestion import IngestionJobs, run_ingestion
from app.ingest.ai_graph import ArchitectureSubmission, check_evidence
from app.ingest.analyzer import TOKEN_CAP_MESSAGE, AnalysisFailed, analyze_repo

ROUTES = """const router = express.Router()

router.get('/users/:id', async (req, res) => {
  const user = await db.user.findUnique({ where: { id: req.params.id } })
  res.json(user)
})

router.post('/orders', async (req, res) => res.json(await db.order.create({ data: req.body })))
"""


def endpoint(path="/users/{id}", file="src/routes.js", line=3, method="GET", effects=None):
    return {"method": method, "path": path, "handler": "h", "file": file, "line": line, "why": "router.get",
            "effects": effects or []}  # fmt: skip


def step(file="src/routes.js", line=4):
    return {"kind": "db", "op": "read", "shape": "pk", "entity": "User", "detail": "db.user.findUnique",
            "file": file, "line": line, "why": "Prisma por id"}  # fmt: skip


def arch(*endpoints, **extra):
    return {"framework": "express", "language": "javascript", "endpoints": list(endpoints), **extra}


def sub(*endpoints, **extra):
    return ArchitectureSubmission.model_validate({**arch(*endpoints, **extra), "repo": "acme/api"})


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "routes.js").write_text(ROUTES)
    return tmp_path


# ---------- check_evidence, una regla por test ----------


def test_valid_evidence_has_no_problems(repo):
    assert check_evidence(sub(endpoint(effects=[step()]), endpoint("/orders", line=8, method="POST")), repo) == []


def test_missing_file(repo):
    [problem] = check_evidence(sub(endpoint(file="src/users.ts")), repo)
    assert problem == "endpoints[0] (GET /users/{id}): 'src/users.ts' no existe en el repo"


def test_dotdot_path_is_rejected_by_the_schema(repo):
    with pytest.raises(ValidationError, match="sin '..'"):
        sub(endpoint(file="../secreto.js"))


def test_symlink_out_of_the_repo(repo, tmp_path_factory):
    outside = tmp_path_factory.mktemp("afuera") / "secret.js"
    outside.write_text("router.get('/users/:id')\n" * 5)
    os.symlink(outside, repo / "src" / "link.js")
    [problem] = check_evidence(sub(endpoint(file="src/link.js", line=1)), repo)
    assert "sale del repo" in problem


def test_line_out_of_range(repo):
    [problem] = check_evidence(sub(endpoint(line=400)), repo)
    assert "tiene 8 líneas, no 400" in problem


def test_path_not_near_the_line(repo):
    [problem] = check_evidence(sub(endpoint("/invoices/{id}")), repo)
    assert "'invoices' no aparece en src/routes.js cerca de la línea 3" in problem and "ni en el resto" in problem


def test_router_prefix_far_from_the_line_is_fine(tmp_path):
    """Lo encontró IA-0: "/{id}" en el decorador y el segmento "items" en el prefix del router, lejos."""
    lines = ['router = APIRouter(prefix="/items")', *["# ..."] * 60, '@router.delete("/{id}")', "def delete_item(id):"]
    (tmp_path / "items.py").write_text("\n".join(lines) + "\n")
    assert (
        check_evidence(sub(endpoint("/api/v1/items/{id}", file="items.py", line=62, method="DELETE")), tmp_path) == []
    )
    # un segmento que no está en ninguna parte del archivo sigue siendo un problema
    assert check_evidence(sub(endpoint("/api/v1/orders/{id}", file="items.py", line=62, method="DELETE")), tmp_path)


def test_root_path_skips_the_segment_check(repo):
    assert check_evidence(sub(endpoint("/", line=1), endpoint("/{id}", line=2)), repo) == []


def test_steps_and_components_are_checked_too(repo):
    s = sub(
        endpoint(effects=[step(line=99)]),
        components=[
            {"name": "redis", "role": "cache", "file": "docker-compose.yml", "line": 1, "why": "redis del compose"}
        ],
    )
    problems = check_evidence(s, repo)
    assert any("paso 0" in p and "no 99" in p for p in problems)
    assert any(p.startswith("components[0] (redis)") for p in problems)


# ---------- analyze_repo ----------


class Scripted:
    model = "claude-opus-5-5"

    def __init__(self, *submissions, usage=None):
        self.submissions, self.errors, self.usage = list(submissions), [], usage or {"input": 10, "output": 1}

    def complete(self, system, messages, tools):
        last = messages[-1]["content"]
        if isinstance(last, list):
            self.errors.append(json.loads(last[0]["content"]).get("error"))
        args = self.submissions.pop(0)
        call = {"type": "tool_use", "id": "s", "name": "submit_architecture", "input": args}
        return Turn([call], "tool_use", dict(self.usage))


def test_false_evidence_goes_back_and_a_fix_has_no_dropped(repo):
    llm = Scripted(arch(endpoint(file="src/users.ts")), arch(endpoint()))
    result = analyze_repo(repo, llm, "acme/api")
    assert "no existe en el repo" in llm.errors[0]
    assert result.dropped == [] and result.sub.endpoints[0].file == "src/routes.js"
    sub_, usage = result  # sigue desempaquetándose como antes
    assert sub_ is result.sub and usage == {"input": 20, "output": 2}


def test_three_bad_submissions_drop_the_bad_endpoint(repo):
    bad = arch(endpoint(), endpoint("/invoices", line=3))
    result = analyze_repo(repo, Scripted(bad, bad, bad), "acme/api")
    assert [e.path for e in result.sub.endpoints] == ["/users/{id}"]
    assert len(result.dropped) == 1 and "GET /invoices" in result.dropped[0]


def test_three_bad_submissions_drop_a_bad_step(repo):
    bad = arch(endpoint(effects=[step(), step(line=99)]))
    result = analyze_repo(repo, Scripted(bad, bad, bad), "acme/api")
    assert len(result.sub.endpoints[0].effects) == 1 and "paso 1" in result.dropped[0]


def test_all_endpoints_false_after_three_is_analysis_failed(repo):
    bad = arch(endpoint(file="no.js"))
    with pytest.raises(AnalysisFailed, match="no citó bien ningún endpoint"):
        analyze_repo(repo, Scripted(bad, bad, bad), "acme/api")


def test_token_cap_stops_the_loop(repo):
    llm = Scripted(arch(endpoint(file="no.js")), arch(endpoint()), usage={"input": 900, "output": 200})
    with pytest.raises(AnalysisFailed) as e:
        analyze_repo(repo, llm, "acme/api", max_tokens_total=1000)
    assert str(e.value) == TOKEN_CAP_MESSAGE


def test_on_step_is_called_once_per_turn(repo):
    seen = []
    analyze_repo(
        repo, Scripted(arch(endpoint(file="no.js")), arch(endpoint())), "acme/api", on_step=lambda *a: seen.append(a)
    )
    assert seen == [(1, "submit_architecture"), (2, "submit_architecture")]


def test_prompt_cache_marks_only_the_last_block():
    messages = [{"role": "user", "content": "repo"}, {"role": "assistant", "content": [{"type": "text", "text": "x"}]},
                {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "a", "content": "{}"}]}]  # fmt: skip
    marked = with_cache_breakpoint(messages)
    assert marked[-1]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in json.dumps(messages)  # no modifica la entrada
    assert with_cache_breakpoint([{"role": "user", "content": "hola"}])[0]["content"] == [
        {"type": "text", "text": "hola", "cache_control": {"type": "ephemeral"}}
    ]


# ---------- la ingesta ----------


class Recording(IngestionJobs):
    def __init__(self):
        super().__init__()
        self.steps: list[int] = []

    def update(self, job_id, **changes):
        if changes.get("llm_steps"):
            self.steps.append(changes["llm_steps"])
        return super().update(job_id, **changes)


def tarball_of(repo):
    import io
    import tarfile

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        tar.add(repo, arcname="acme-api-abc1234")
    return buf.getvalue()


class FakeGitHub:
    def __init__(self, data):
        self.data = data

    def fetch(self, installation_id, full_name, ref):
        return "06ff98cfa9b925e35b866e5abdf9e792006a36bb", self.data


def run(repo, llm, store=None, **kw):
    from app.api.store import InMemoryProjectStore
    from app.github.client import Repo

    jobs, store = Recording(), store or InMemoryProjectStore()
    job = jobs.start(None, "acme/api", "main")
    run_ingestion(jobs, job.id, FakeGitHub(tarball_of(repo)), store, Repo(1, "acme/api", False, "main", 1),
                  "api", llm, **kw)  # fmt: skip
    return jobs, jobs.get(job.id, None), store


def test_ingestion_reports_steps_cost_and_dropped(repo):
    bad = arch(endpoint(), endpoint("/invoices", line=3))
    jobs, job, store = run(repo, Scripted(bad, bad, bad))
    assert job.status == "done", job.error_message
    assert jobs.steps == [1, 2, 3]  # crece vuelta a vuelta
    assert job.llm_steps == 3 and job.cost["label"] == "ESTIMADO"
    analysis = store.get_version(job.project_id, 1).model["repo"]["source"]["analysis"]
    assert analysis["steps"] == 3 and "GET /invoices" in analysis["dropped"][0]


def test_token_cap_in_the_ingestion_fails_with_the_branchpoint_message(repo):
    llm = Scripted(arch(endpoint(file="no.js")), usage={"input": 2000, "output": 1})
    _, job, _ = run(repo, llm, max_tokens_total=1000)
    assert job.status == "failed" and job.error_message == TOKEN_CAP_MESSAGE


def test_provider_auth_error_names_the_provider_not_the_key(repo):
    class Rejected:
        model = "claude-opus-5-5"

        def complete(self, system, messages, tools):
            request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
            response = httpx.Response(401, request=request, json={"error": {"type": "authentication_error"}})
            raise anthropic.AuthenticationError("invalid x-api-key sk-ant-secreta", response=response, body=None)

    _, job, _ = run(repo, Rejected())
    assert job.status == "failed"
    assert job.error_message.startswith("Anthropic rechazó la autenticación")
    assert "sk-ant-secreta" not in job.error_message
