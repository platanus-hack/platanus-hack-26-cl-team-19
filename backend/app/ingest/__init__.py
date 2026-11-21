"""Ingesta determinista del repo del usuario (ADR 0001, paso 1).

* ``iac``: archivos de despliegue (Compose, Dockerfile, Kubernetes, fly.toml, render.yaml, Terraform)
  → servicios y números del ``deployment`` con procedencia ``OBSERVADO`` (JAJ-60).

El extractor del grafo (``spikes/jaj-7-ingestion/extract.py``) y ``build_model.py`` se mueven aquí en
JAJ-57.
"""

from app.ingest.iac import Findings, Service, scan_deployment

__all__ = ["Findings", "Service", "scan_deployment"]
