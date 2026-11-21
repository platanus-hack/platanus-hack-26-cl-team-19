"""Costos de una arquitectura (JAJ-72): precios fechados de JAJ-11 y el costo mensual por componente.

* ``prices``: los snapshots de precios (``prices/aws.json``, ``prices/manual.json``) con su fuente.
* ``estimate``: ``estimate_cost(modelo)`` → costo mensual por componente con procedencia, y
  ``cost_delta(a, b)`` para comparar dos versiones.
"""

from app.costs.estimate import CostDelta, CostEstimate, CostLine, cost_delta, estimate_cost

__all__ = ["CostDelta", "CostEstimate", "CostLine", "cost_delta", "estimate_cost"]
