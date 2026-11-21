"""Grafo del diagrama del editor, derivado de un modelo ``branchpoint.model/v1``.

El modelo describe endpoints y sus pasos, no cajas y flechas. Aquí se arma lo que dibuja el editor:

* Nodos: la API, y la DB, caché, servicio externo, colas y sus workers que usa algún paso.
* Aristas: quién llama a quién, con los endpoints que pasan por ahí y las líneas de código
  (``at``) de cada llamada, para que el banner del cuello de botella pueda apuntar al código.

Los ids de nodo coinciden con los recursos del ``Run`` cuando existen (``db_cpu`` y ``db_pool``
son de ``db``; ``api_cpu`` y ``api_threads`` de ``api``; ``queue:<nombre>`` de su cola).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from typing import Any

from app.models.architecture import (
    RESOURCE_BACKGROUND,
    RESOURCE_CACHE,
    RESOURCE_DB_CONNECTION,
    ArchitectureModel,
    Step,
    value,
    walk_steps,
)

RESOURCE_EXTERNAL = "external"

# recurso de un paso -> nodo al que apunta la arista
_TARGET = {
    RESOURCE_DB_CONNECTION: ("db", "db", "Base de datos"),
    RESOURCE_CACHE: ("cache", "cache", "Caché"),
    RESOURCE_EXTERNAL: ("external", "external", "Servicio externo"),
}

# recursos del Run que pertenecen a cada nodo
_RUN_RESOURCES = {"api": ["api_cpu", "api_threads"], "db": ["db_cpu", "db_pool"]}


@dataclass
class GraphEndpoint:
    id: str
    method: str | None
    path: str | None
    at: str | None
    weight: float  # fracción del tráfico (0 a 1)


@dataclass
class GraphNode:
    id: str
    kind: str  # api, db, cache, external, queue, worker
    label: str
    resources: list[str] = field(default_factory=list)  # recursos del Run de este nodo
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphEdge:
    id: str
    source: str
    target: str
    endpoints: list[str]  # endpoints (o "cola <nombre>") cuyos pasos usan esta arista
    calls: int  # llamadas por request sumando repeat (N+1), en el peor caso de la caché
    refs: list[str]  # archivo:línea de cada llamada, sin repetir


@dataclass
class Graph:
    model: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    endpoints: list[GraphEndpoint]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class _EdgeAcc:
    def __init__(self, source: str, target: str) -> None:
        self.source, self.target = source, target
        self.endpoints: list[str] = []
        self.calls = 0
        self.refs: list[str] = []

    def add(self, who: str, step: Step) -> None:
        if who not in self.endpoints:
            self.endpoints.append(who)
        self.calls += step.repeat
        if step.at and step.at not in self.refs:
            self.refs.append(step.at)


def build_graph(model: ArchitectureModel, raw: dict[str, Any]) -> Graph:
    dep = raw.get("deployment", {})
    api_raw, db_raw = dep.get("api", {}), dep.get("db", {})
    nodes: dict[str, GraphNode] = {
        "api": GraphNode(
            id="api",
            kind="api",
            label="API",
            resources=list(_RUN_RESOURCES["api"]),
            details={
                "provider": api_raw.get("provider"),
                "replicas": model.api.replicas,
                "vcpu": model.api.vcpu,
                "workers": model.api.workers,
                "threads": model.api.threads,
            },
        )
    }
    edges: dict[tuple[str, str], _EdgeAcc] = {}

    def node_for(resource: str | None, queue: str | None) -> str | None:
        if resource in _TARGET:
            node_id, kind, label = _TARGET[resource]
            if node_id not in nodes:
                details: dict[str, Any] = {}
                resources: list[str] = []
                if kind == "db":
                    resources = list(_RUN_RESOURCES["db"])
                    details = {
                        "provider": db_raw.get("provider"),
                        "plan": db_raw.get("plan"),
                        "vcpu": model.db.vcpu,
                        "max_connections": model.db.max_connections,
                        "app_connections": model.app_connections,
                    }
                nodes[node_id] = GraphNode(node_id, kind, label, resources, details)
            return node_id
        if resource == RESOURCE_BACKGROUND:
            node_id = f"queue:{queue}" if queue else "queue"
            if node_id not in nodes:
                q = model.queues.get(queue) if queue else None
                nodes[node_id] = GraphNode(
                    node_id,
                    "queue",
                    f"Cola {queue}" if queue else "Cola (sin configurar)",
                    [node_id] if q else [],
                    {"max_length": q.max_length} if q else {"configured": False},
                )
            return node_id
        return None  # CPU de la API u otra espera: no sale del nodo

    def add_steps(source: str, who: str, steps: Iterable[Step]) -> None:
        for step in steps:
            target = node_for(step.resource, step.queue)
            if target is None:
                continue
            edges.setdefault((source, target), _EdgeAcc(source, target)).add(who, step)

    raw_by_id = {e.get("id"): e for e in raw.get("endpoints", [])}
    graph_endpoints = []
    for ep in model.endpoints:
        add_steps("api", ep.id, walk_steps(ep.steps))
        r = raw_by_id.get(ep.id, {})
        graph_endpoints.append(GraphEndpoint(ep.id, r.get("method"), r.get("path"), r.get("at"), ep.weight))

    for name, q in model.queues.items():
        queue_id = node_for(RESOURCE_BACKGROUND, name)
        worker_id = f"worker:{name}"
        nodes[worker_id] = GraphNode(worker_id, "worker", f"Workers de {name}", [], {"workers": q.workers})
        edges[(queue_id, worker_id)] = _EdgeAcc(queue_id, worker_id)
        add_steps(worker_id, f"cola {name}", walk_steps(q.job_steps))

    return Graph(
        model=model.name,
        nodes=list(nodes.values()),
        edges=[
            GraphEdge(f"{e.source}->{e.target}", e.source, e.target, e.endpoints, e.calls, e.refs)
            for e in edges.values()
        ],
        endpoints=graph_endpoints,
    )


def model_summary(raw: dict[str, Any], model: ArchitectureModel) -> dict[str, Any]:
    """Lo mínimo para listar un modelo: repo, despliegue, escenarios y tamaño."""
    dep = raw.get("deployment", {})
    return {
        "name": model.name,
        "extracted_at": raw.get("repo", {}).get("extracted_at"),
        "api_provider": dep.get("api", {}).get("provider"),
        "db_provider": dep.get("db", {}).get("provider"),
        "db_plan": dep.get("db", {}).get("plan"),
        "endpoints": len(model.endpoints),
        "scenarios": {name: sc.rps for name, sc in model.scenarios.items()},
        "mau": value(raw.get("traffic", {}).get("mau")),
    }
