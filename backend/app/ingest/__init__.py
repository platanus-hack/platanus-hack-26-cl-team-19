"""Ingesta determinista del repo del usuario (ADR 0001, paso 1).

* ``iac``: archivos de despliegue (Compose, Dockerfile, Kubernetes, fly.toml, render.yaml, Terraform)
  → servicios y números del ``deployment`` con procedencia ``OBSERVADO`` (JAJ-60).

* ``extract``: el grafo del repo desde el AST (endpoints, accesos a DB, riesgos), de JAJ-7.
* ``build_model``: cruza el grafo, ``iac`` y el catálogo y arma el ``branchpoint.model/v1`` (JAJ-45).

Los dos se movieron de ``spikes/`` en JAJ-57. Los de ``spikes/`` quedan como registro de la
investigación: el backend usa estos.
"""

from app.ingest.iac import Findings, Service, scan_deployment

__all__ = ["Findings", "Service", "scan_deployment"]
