"""Del repo del usuario al modelo, sin importar el framework (ADR 0002).

* ``analyzer``: Claude lee el repo en la ingesta de GitHub y propone su arquitectura.
* ``ai_graph``: el schema de esa propuesta (el mismo de la tool MCP ``submit_architecture``) y su
  conversión al grafo intermedio.
* ``iac``: archivos de despliegue (Compose, Dockerfile, Kubernetes, fly.toml, render.yaml, Terraform)
  → servicios y números del ``deployment`` con procedencia ``OBSERVADO`` (JAJ-60).
* ``build_model``: cruza el grafo, ``iac`` y el catálogo y arma el ``branchpoint.model/v1`` (JAJ-45).
"""

from app.ingest.iac import Findings, Service, scan_deployment

__all__ = ["Findings", "Service", "scan_deployment"]
