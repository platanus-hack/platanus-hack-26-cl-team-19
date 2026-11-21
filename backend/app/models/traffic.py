"""Perfil de tráfico en el tiempo (JAJ-71): cómo cambia la tasa de llegadas durante la simulación.

Sin perfil, el motor simula una tasa constante (las req/s del escenario, o ``rps``). Con perfil, la
tasa sigue tramos en orden. Cada tramo dura ``duration_s`` segundos y va linealmente de
``from_multiplier`` a ``to_multiplier`` veces la tasa base:

    [{"duration_s": 60, "from_multiplier": 0.35, "to_multiplier": 1},   # subida
     {"duration_s": 120, "from_multiplier": 1, "to_multiplier": 1},     # meseta
     {"duration_s": 60, "from_multiplier": 1, "to_multiplier": 0.5}]    # bajada

Así la serie por segundo del ``Run`` muestra cómo se llena la cola en el tramo alto y cómo se vacía
en la bajada, que es lo que dibuja ``SimulationChart`` en el editor.

``preset("pico", duración)`` arma la forma que usa el editor en sus datos de ejemplo: 25 % de subida
de 0,35 a 1, 45 % de meseta y 30 % de bajada hasta 0,5. La forma (cuánto dura cada tramo y a qué
fracción del pico llega) es una elección de diseño para mostrar un evento, no una medición: en
JAJ-59 el usuario la va a poder dar en el chat.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

MAX_SEGMENTS = 50


@dataclass(frozen=True)
class TrafficSegment:
    duration_s: float
    from_multiplier: float
    to_multiplier: float

    def __post_init__(self) -> None:
        if self.duration_s <= 0:
            raise ValueError("Cada tramo del perfil de tráfico debe durar más de 0 s")
        if self.from_multiplier < 0 or self.to_multiplier < 0:
            raise ValueError("Los multiplicadores del perfil de tráfico no pueden ser negativos")


@dataclass(frozen=True)
class TrafficProfile:
    """Tramos en orden. ``rate_at(t)`` es el multiplicador en el segundo ``t`` (0 después del final)."""

    segments: tuple[TrafficSegment, ...]

    def __post_init__(self) -> None:
        if not self.segments:
            raise ValueError("El perfil de tráfico necesita al menos un tramo")
        if len(self.segments) > MAX_SEGMENTS:
            raise ValueError(f"El perfil de tráfico puede tener hasta {MAX_SEGMENTS} tramos")
        if self.peak <= 0:
            raise ValueError("El perfil de tráfico tiene multiplicador 0 en todos los tramos: no llega nadie")

    @property
    def duration_s(self) -> float:
        return sum(s.duration_s for s in self.segments)

    @property
    def peak(self) -> float:
        return max(max(s.from_multiplier, s.to_multiplier) for s in self.segments)

    @property
    def mean(self) -> float:
        """Multiplicador promedio en el tiempo (para estimar cuántas requests se simulan)."""
        area = sum(s.duration_s * (s.from_multiplier + s.to_multiplier) / 2 for s in self.segments)
        return area / self.duration_s

    def multiplier_at(self, t: float) -> float:
        start = 0.0
        for s in self.segments:
            if t < start + s.duration_s:
                frac = (t - start) / s.duration_s
                return s.from_multiplier + (s.to_multiplier - s.from_multiplier) * frac
            start += s.duration_s
        return 0.0

    def slope_at(self, t: float) -> float:
        """Cuánto cambia el multiplicador por segundo en el tramo de ``t`` (0 después del final)."""
        start = 0.0
        for s in self.segments:
            if t < start + s.duration_s:
                return (s.to_multiplier - s.from_multiplier) / s.duration_s
            start += s.duration_s
        return 0.0

    def next_change(self, t: float) -> float:
        """El próximo borde de tramo después de ``t`` (o el final del perfil)."""
        start = 0.0
        for s in self.segments:
            start += s.duration_s
            if t < start:
                return start
        return start

    @classmethod
    def from_dicts(cls, items: Sequence[dict]) -> TrafficProfile:
        return cls(
            tuple(
                TrafficSegment(float(i["duration_s"]), float(i["from_multiplier"]), float(i["to_multiplier"]))
                for i in items
            )
        )


PRESETS = ("pico",)


def preset(name: str, duration_s: float) -> TrafficProfile:
    """Perfil con nombre, escalado a ``duration_s``. ``pico``: subida, meseta y bajada (ver el docstring)."""
    if name != "pico":
        raise ValueError(f"Perfil desconocido: '{name}'. Hay: {', '.join(PRESETS)}")
    if duration_s <= 0:
        raise ValueError("duration_s debe ser mayor que 0")
    return TrafficProfile(
        (
            TrafficSegment(duration_s * 0.25, 0.35, 1.0),
            TrafficSegment(duration_s * 0.45, 1.0, 1.0),
            TrafficSegment(duration_s * 0.30, 1.0, 0.5),
        )
    )
