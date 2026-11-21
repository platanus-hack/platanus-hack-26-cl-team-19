"""Costos de una arquitectura (JAJ-72): precios fechados de JAJ-11 y el costo mensual por componente.

* ``prices``: los snapshots de precios (``prices/aws.json``, ``prices/manual.json``) con su fuente.
* ``estimate``: ``estimate_cost(modelo)`` → costo mensual por componente con procedencia, y
  ``cost_delta(a, b)`` para comparar dos versiones.
* ``failure``: ``failure_cost(modelo, run)`` → ventas en juego por hora según la tasa de error del
  ``Run``, como rango (JAJ-74).
"""

from app.costs.estimate import CostDelta, CostEstimate, CostLine, cost_delta, estimate_cost
from app.costs.failure import FailureCost, failure_cost

__all__ = ["CostDelta", "CostEstimate", "CostLine", "FailureCost", "cost_delta", "estimate_cost", "failure_cost"]
