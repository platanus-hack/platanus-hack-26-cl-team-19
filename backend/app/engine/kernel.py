"""Kernel de simulación de eventos discretos con heap propio (decisión de JAJ-9).

Cada proceso es un generador que cede comandos al kernel:

* un número: esperar esa cantidad de segundos;
* ``resource.acquire(timeout)``: tomar un lugar del recurso. El generador recibe ``True`` si lo
  consiguió o ``False`` si se cumplió el timeout esperando en la cola.

Los recursos son FIFO y cuentan su uso en el tiempo, la cola máxima y los timeouts. Con la misma
semilla, la simulación es determinista: el heap desempata por orden de llegada.
"""

from __future__ import annotations

import heapq
import random
from collections import deque
from collections.abc import Callable, Generator
from typing import Any

Process = Generator[Any, Any, None]


class SimulationTooLarge(ValueError):
    """La corrida pasó su presupuesto de eventos (JAJ-99). Es un ``ValueError`` para que quien ya
    captura los errores de parámetros (la API, el CLI) lo maneje igual, pero la API lo distingue
    para responder ``run_too_large``."""

    def __init__(self, max_events: int) -> None:
        self.max_events = max_events
        limit = f"{max_events:,}".replace(",", ".")
        super().__init__(
            f"La simulación pasó el máximo de {limit} eventos y se detuvo. El modelo hace demasiado "
            "trabajo por request (pasos repetidos o trabajos que se encolan sin fin): revisa sus "
            "pasos, o baja la duración o la tasa."
        )


class Sim:
    """Reloj, cola de eventos y generador de números aleatorios de una corrida."""

    def __init__(self, seed: int = 0) -> None:
        self.now = 0.0
        self.rng = random.Random(seed)
        self._heap: list[tuple[float, int, Callable[[Any], None], Any]] = []
        self._seq = 0

    def at(self, t: float, fn: Callable[[Any], None], arg: Any = None) -> None:
        """Programa ``fn(arg)`` en el instante ``t``."""
        self._seq += 1
        heapq.heappush(self._heap, (t, self._seq, fn, arg))

    def start(self, process: Process) -> None:
        """Arranca un proceso en el instante actual."""
        self.at(self.now, self._resume, (process, None))

    def run(self, until: float | None = None, max_events: int | None = None) -> None:
        """Procesa eventos hasta vaciar la cola o hasta ``until`` (los posteriores quedan pendientes).

        ``max_events`` es el presupuesto de la corrida (JAJ-99): al pasarlo lanza
        ``SimulationTooLarge``. Sin él, un proceso que se reprograma en el mismo instante (el reloj
        no avanza) no termina nunca."""
        heap, pop = self._heap, heapq.heappop
        left = max_events if max_events is not None else -1
        while heap:
            if until is not None and heap[0][0] > until:
                self.now = until
                return
            if left == 0:
                raise SimulationTooLarge(max_events)
            left -= 1
            t, _, fn, arg = pop(heap)
            self.now = t
            fn(arg)

    def _resume(self, item: tuple[Process, Any]) -> None:
        process, value = item
        try:
            cmd = process.send(value)
        except StopIteration:
            return
        if cmd.__class__ is float or cmd.__class__ is int:
            self.at(self.now + cmd, self._resume, (process, None))
        else:
            cmd(self, process)


class Resource:
    """Recurso con ``capacity`` lugares y cola FIFO (núcleos, conexiones de un pool, hilos)."""

    def __init__(self, sim: Sim, name: str, capacity: int) -> None:
        if capacity < 1:
            raise ValueError(f"{name}: la capacidad debe ser al menos 1 (es {capacity})")
        self.sim = sim
        self.name = name
        self.capacity = capacity
        self.busy = 0
        self.waiting = 0
        self.max_waiting = 0
        self.timeouts = 0
        self.grants = 0
        self.wait_total = 0.0
        self._queue: deque[list[Any]] = deque()
        self._area = 0.0
        self._last = 0.0

    def acquire(self, timeout: float | None = None) -> Callable[[Sim, Process], None]:
        """Comando para ``yield``: el proceso recibe True al obtener un lugar, False si vence ``timeout``."""

        def cmd(sim: Sim, process: Process) -> None:
            if self.busy < self.capacity and not self.waiting:
                self._touch()
                self.busy += 1
                self.grants += 1
                sim._resume((process, True))
                return
            waiter = [process, True, sim.now]  # proceso, sigue esperando, desde cuándo
            self._queue.append(waiter)
            self.waiting += 1
            if self.waiting > self.max_waiting:
                self.max_waiting = self.waiting
            if timeout is not None:
                sim.at(sim.now + timeout, self._expire, waiter)

        return cmd

    def release(self) -> None:
        """Libera un lugar; si hay alguien esperando, se lo pasa directamente."""
        self._touch()
        while self._queue:
            waiter = self._queue.popleft()
            if waiter[1]:
                waiter[1] = False
                self.waiting -= 1
                self.grants += 1
                self.wait_total += self.sim.now - waiter[2]
                self.sim.at(self.sim.now, self.sim._resume, (waiter[0], True))
                return
        self.busy -= 1

    def busy_time(self) -> float:
        """Integral de lugares ocupados en el tiempo, hasta ``sim.now``."""
        self._touch()
        return self._area

    def _touch(self) -> None:
        now = self.sim.now
        self._area += self.busy * (now - self._last)
        self._last = now

    def _expire(self, waiter: list[Any]) -> None:
        if waiter[1]:
            waiter[1] = False
            self.waiting -= 1
            self.timeouts += 1
            self.wait_total += self.sim.now - waiter[2]  # esperó hasta vencer (JAJ-135)
            self.sim._resume((waiter[0], False))

    def mean_wait(self) -> float:
        """Espera media en segundos de todos los que pidieron un lugar hasta ``sim.now`` (JAJ-135):

        * quienes lo obtuvieron, hasta obtenerlo (0 si había lugar libre);
        * quienes vencieron, hasta vencer;
        * quienes siguen en la cola, hasta ahora.

        Antes solo contaba a quienes lo obtuvieron: en saturación, con timeouts o cola al final, quedaba
        muy por debajo de la espera real."""
        now = self.sim.now
        queued = [now - w[2] for w in self._queue if w[1]]
        total = self.grants + self.timeouts + len(queued)
        return (self.wait_total + sum(queued)) / total if total else 0.0
