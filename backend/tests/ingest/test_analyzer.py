"""Claude lee el repo en la ingesta (ADR 0002): las tools de lectura, la validación y los límites."""

import json

import pytest

from app.agent.loop import Turn
from app.ingest.analyzer import AnalysisFailed, RepoReader, analyze_repo

ARCH = {
    "framework": "gin",
    "language": "go",
    "endpoints": [
        {
            "method": "GET",
            "path": "/health",
            "handler": "health",
            "file": "main.go",
            "line": 3,
            "why": "r.GET",
            "effects": [],
        }
    ],
}


class Scripted:
    """Devuelve las tool calls en orden y guarda los tool_result que recibe."""

    model = "claude-opus-5-5"

    def __init__(self, *calls):
        self.calls, self.results = list(calls), []

    def complete(self, system, messages, tools):
        if isinstance(messages[-1]["content"], list):
            self.results.append([json.loads(r["content"]) for r in messages[-1]["content"]])
        name, args = self.calls.pop(0)
        return Turn([{"type": "tool_use", "id": f"t{len(self.calls)}", "name": name, "input": args}], "tool_use",
                    {"input": 10, "output": 1})  # fmt: skip


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "main.go").write_text('package main\n\nfunc main() { r.GET("/health", health) }\n')
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.js").write_text("app.get('/no')\n")
    return tmp_path


def test_reads_the_repo_and_returns_a_valid_submission(repo):
    llm = Scripted(("grep", {"pattern": r"\.GET\("}), ("read_file", {"path": "main.go"}), ("submit_architecture", ARCH))
    sub, usage = analyze_repo(repo, llm, "acme/api", "abc1234")
    assert (sub.repo, sub.commit, sub.framework) == ("acme/api", "abc1234", "gin")  # repo y commit del servidor
    assert llm.results[0][0]["hits"] == ['main.go:3: func main() { r.GET("/health", health) }']  # sin node_modules
    assert "3\tfunc main()" in llm.results[1][0]["content"]
    assert usage == {"input": 30, "output": 3}


def test_invalid_submission_goes_back_to_the_llm(repo):
    bad = {**ARCH, "endpoints": [{**ARCH["endpoints"][0], "latency_ms": 5}]}
    llm = Scripted(("submit_architecture", bad), ("submit_architecture", ARCH))
    sub, _ = analyze_repo(repo, llm, "acme/api")
    assert "latency_ms" in llm.results[0][0]["error"] and sub.endpoints[0].path == "/health"


def test_paths_cannot_leave_the_repo(repo):
    reader = RepoReader(repo)
    with pytest.raises(ValueError, match="sale del repo"):
        reader.read_file("../../etc/passwd")
    llm = Scripted(("read_file", {"path": "../secreto"}), ("submit_architecture", ARCH))
    analyze_repo(repo, llm, "acme/api")
    assert "sale del repo" in llm.results[0][0]["error"]


def test_gives_up_after_the_iteration_limit(repo):
    llm = Scripted(*[("list_files", {})] * 3)
    with pytest.raises(AnalysisFailed, match="3 pasos"):
        analyze_repo(repo, llm, "acme/api", max_iterations=3)
