"""Motor de simulación de eventos discretos (JAJ-14).

* ``kernel``: reloj, cola de eventos y recursos (genérico, no sabe de APIs ni de DBs).
* ``simulate``: arma los recursos desde un modelo de arquitectura y recorre los pasos de cada request.
* ``metrics``: percentiles y series por segundo.
"""

from app.engine.kernel import Resource, Sim
from app.engine.simulate import simulate

__all__ = ["Resource", "Sim", "simulate"]
