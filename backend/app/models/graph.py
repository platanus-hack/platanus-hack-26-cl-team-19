"""Grafo del diagrama del editor, derivado de un modelo ``branchpoint.model/v1``.

El modelo describe endpoints y sus pasos, no cajas y flechas. Aquí se arma lo que dibuja el editor:

* Nodos: la API, y la DB, caché, servicio externo, colas y sus workers que usa algún paso.
  Si la IA del usuario propuso la arquitectura (JAJ-85, JAJ-86), cada servicio externo es un nodo con
  su nombre, y los componentes que declaró (``deployment.services`` con ``origin``) aparecen aunque
  ningún paso los use, con su tecnología, su ``archivo:línea`` y su procedencia en ``details``.
* Aristas: quién llama a quién, con los endpoints que pasan por ahí y las líneas de código
  (``at``) de cada llamada, para que el banner del cuello de botella pueda apuntar al código.

Con varios repos (IA-5), cada nodo trae ``repo`` y ``simulated``: el motor simula el repo principal, y cada
repo secundario es un nodo ``service:<repo>`` (con sus componentes) que no se simula. En un proyecto de un
solo repo, ``repo`` es ``None`` y todo queda ``simulated: true``, como antes.

Los ids de nodo coinciden con los recursos del ``Run`` cuando existen (``db_cpu`` y ``db_pool``
son de ``db``; ``api_cpu`` y ``api_threads`` de ``api``; ``queue:<nombre>`` de su cola; ``replica_cpu:<i>`` y
``replica_pool:<i>`` del nodo ``db_replica``, que junta las réplicas de lectura, JAJ-140).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from typing import Any

from app.models.architecture import (
    READ_SHAPES,
    RESOURCE_BACKGROUND,
    RESOURCE_CACHE,
    RESOURCE_DB_CONNECTION,
    ArchitectureModel,
    Step,
    value,
    walk_steps,
)
from app.models.overrides import slowdown_targets

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
    kind: str  # api, db, cache, external, queue, worker; de la IA también storage, search, other
    label: str
    resources: list[str] = field(default_factory=list)  # recursos del Run de este nodo
    details: dict[str, Any] = field(default_factory=dict)
    repo: str | None = None  # el repo del componente, solo en proyectos de varios repos (IA-5)
    simulated: bool = True  # false: viene de un repo secundario y el motor no lo simula


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
    slowdown_targets: list[str] = field(default_factory=list)

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


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "servicio"


def _component_details(component: dict[str, Any] | None) -> dict[str, Any]:
    if not component:
        return {}
    return {
        k: v
        for k, v in (
            ("technology", component.get("engine")),
            ("at", component.get("at")),
            ("origin", component.get("origin")),
            ("endpoints", component.get("endpoints")),
            ("error", component.get("error")),
        )
        if v is not None and v != ""
    }


def _secondary_id(component: dict[str, Any]) -> str:
    if component.get("role") == "service":
        return f"service:{_slug(component['name'])}"
    return f"component:{_slug(component.get('repo') or '')}:{_slug(component['name'])}"


def build_graph(model: ArchitectureModel, raw: dict[str, Any]) -> Graph:
    dep = raw.get("deployment", {})
    # Componentes que propuso la IA, y el servicio con nombre de cada llamada externa (archivo:línea)
    ai_components = [s for s in dep.get("services", []) if s.get("origin")]
    by_name = {s["name"].lower(): s for s in ai_components}
    service_at = {
        step["at"]: step["service"]
        for ep in raw.get("endpoints", [])
        for step in ep.get("steps", [])
        if step.get("service") and step.get("at")
    }
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

    def node_for(resource: str | None, queue: str | None, at: str | None = None) -> str | None:
        if resource == RESOURCE_EXTERNAL and at in service_at:
            name = service_at[at]
            component = by_name.get(name.lower())
            if component and component.get("role") == "service":  # un repo secundario (IA-5)
                node_id = _secondary_id(component)
                if node_id not in nodes:
                    nodes[node_id] = GraphNode(
                        node_id, "service", name, [], _component_details(component), component.get("repo"), False
                    )
                return node_id
            node_id = f"external:{_slug(name)}"
            if node_id not in nodes:
                details = _component_details(component)
                nodes[node_id] = GraphNode(node_id, "external", name, [], details)
            return node_id
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

    def replica_node() -> str:
        """JAJ-140: las réplicas de lectura, un solo nodo con los recursos de todas."""
        n = model.db.read_replicas
        if "db_replica" not in nodes:
            replica_raw = db_raw.get("read_replicas") or {}
            nodes["db_replica"] = GraphNode(
                "db_replica",
                "db",
                f"Réplica de lectura ×{n}",
                [f"{prefix}{i}" for i in range(1, n + 1) for prefix in ("replica_cpu:", "replica_pool:")],
                {
                    "provider": db_raw.get("provider"),
                    "plan": replica_raw.get("plan", db_raw.get("plan")),
                    "vcpu": model.db.replica_vcpu,
                    "replicas": n,
                },
            )
        return "db_replica"

    def add_steps(source: str, who: str, steps: Iterable[Step], replica_reads: bool = False) -> None:
        for step in steps:
            if replica_reads and step.resource == RESOURCE_DB_CONNECTION and step.shape in READ_SHAPES:
                target: str | None = replica_node()
            else:
                target = node_for(step.resource, step.queue, step.at)
            if target is None:
                continue
            edges.setdefault((source, target), _EdgeAcc(source, target)).add(who, step)

    raw_by_id = {e.get("id"): e for e in raw.get("endpoints", [])}
    graph_endpoints = []
    for ep in model.endpoints:
        # las requests leen de las réplicas; los trabajos de las colas, de la primaria (como el motor)
        add_steps("api", ep.id, walk_steps(ep.steps), replica_reads=model.db.read_replicas > 0)
        r = raw_by_id.get(ep.id, {})
        graph_endpoints.append(GraphEndpoint(ep.id, r.get("method"), r.get("path"), r.get("at"), ep.weight))

    for name, q in model.queues.items():
        queue_id = node_for(RESOURCE_BACKGROUND, name)
        worker_id = f"worker:{name}"
        nodes[worker_id] = GraphNode(worker_id, "worker", f"Workers de {name}", [], {"workers": q.workers})
        edges[(queue_id, worker_id)] = _EdgeAcc(queue_id, worker_id)
        add_steps(worker_id, f"cola {name}", walk_steps(q.job_steps))

    for component in ai_components:
        role, details = component.get("role"), _component_details(component)
        if component.get("simulated") is False:  # de un repo secundario: su propio nodo, nunca el del principal
            node_id = _secondary_id(component)
            if node_id not in nodes:
                kind = "service" if role == "service" else role
                nodes[node_id] = GraphNode(node_id, kind, component["name"], [], details, component.get("repo"), False)
            continue
        if role in ("db", "cache") and role in nodes:
            nodes[role].details.update({k: v for k, v in details.items() if k not in nodes[role].details})
            continue
        if role == "external":
            node_id = f"external:{_slug(component['name'])}"
        elif role in ("db", "cache"):
            node_id = role
        else:
            node_id = f"component:{_slug(component['name'])}"
        if node_id not in nodes:
            nodes[node_id] = GraphNode(node_id, role, component["name"], [], details)

    sources = (raw.get("repo") or {}).get("sources") or []
    if len(sources) > 1:  # varios repos: lo simulado es del principal
        primary = next((src["full_name"] for src in sources if src.get("primary")), None)
        for node in nodes.values():
            if node.simulated and node.repo is None:
                node.repo = primary
    return Graph(
        model=model.name,
        nodes=list(nodes.values()),
        edges=[
            GraphEdge(f"{e.source}->{e.target}", e.source, e.target, e.endpoints, e.calls, e.refs)
            for e in edges.values()
        ],
        endpoints=graph_endpoints,
        slowdown_targets=slowdown_targets(raw),
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
