"""Reportes de simulación (JAJ-127): una foto congelada de cada corrida, para leerla, exportarla y compararla.

* ``build_report``: el reporte de una corrida (``branchpoint.report/v1``, ``kind: "run"``).
* ``build_comparison``: dos reportes ya guardados lado a lado, sin volver a simular (``kind: "comparison"``).
* ``to_markdown``: el mismo reporte en Markdown, para pegarlo en Slack, GitHub o un documento.

Los números salen del ``Run``, de ``estimate_cost`` y de ``failure_cost``: nada lo escribe un LLM. La
conclusión es una plantilla. El diagnóstico por componente y el margen hasta saturar son datos estructurados,
para que más adelante se puedan usar al decidir cambios de arquitectura.
"""

from app.reports.build import REPORT_SCHEMA, build_comparison, build_report
from app.reports.markdown import to_markdown

__all__ = ["REPORT_SCHEMA", "build_comparison", "build_report", "to_markdown"]
