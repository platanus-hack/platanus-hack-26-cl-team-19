"""Tests del kernel: orden FIFO, timeouts y validación contra la fórmula de colas M/M/c (Erlang C)."""

import math

from app.engine.kernel import Resource, Sim


def test_fifo_and_timeout():
    sim = Sim(seed=0)
    res = Resource(sim, "r", capacity=1)
    log = []

    def holder():
        yield res.acquire()
        log.append(("A toma", sim.now))
        yield 10.0
        res.release()

    def impatient():
        yield 1.0
        got = yield res.acquire(timeout=2.0)
        log.append(("B", got, sim.now))

    def patient():
        yield 1.5
        got = yield res.acquire()
        log.append(("C", got, sim.now))
        res.release()

    for p in (holder(), impatient(), patient()):
        sim.start(p)
    sim.run()

    assert log == [("A toma", 0.0), ("B", False, 3.0), ("C", True, 10.0)]
    assert res.timeouts == 1
    assert res.busy == 0 and res.waiting == 0


def erlang_c_wait(lam: float, mu: float, c: int) -> float:
    """Espera media en cola (Wq) de una M/M/c."""
    a = lam / mu
    rho = a / c
    tail = a**c / math.factorial(c) / (1 - rho)
    p_wait = tail / (sum(a**k / math.factorial(k) for k in range(c)) + tail)
    return p_wait / (c * mu - lam)


def test_matches_erlang_c():
    """1 servicio con 3 servidores al 80 % de uso: la espera media coincide con la fórmula (±5 %)."""
    lam, mu, c, n = 2.4, 1.0, 3, 100_000
    sim = Sim(seed=42)
    res = Resource(sim, "servidores", capacity=c)
    waits = []

    def customer():
        t0 = sim.now
        yield res.acquire()
        waits.append(sim.now - t0)
        yield sim.rng.expovariate(mu)
        res.release()

    def arrivals():
        for _ in range(n):
            yield sim.rng.expovariate(lam)
            sim.start(customer())

    sim.start(arrivals())
    sim.run()

    expected = erlang_c_wait(lam, mu, c)
    measured = sum(waits) / len(waits)
    assert abs(measured - expected) / expected < 0.05, f"Wq simulado {measured:.3f} vs fórmula {expected:.3f}"
