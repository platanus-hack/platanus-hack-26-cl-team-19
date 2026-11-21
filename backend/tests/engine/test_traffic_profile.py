"""Tests del perfil de tráfico en el tiempo (JAJ-71).

Sistema sintético: 1 núcleo de API y 10 ms de CPU por request → capacidad de 100 req/s.
"""

import pytest

from app.engine import simulate
from app.models import load_model
from app.models.traffic import TrafficProfile, TrafficSegment, preset
from app.samples import load_sample

CAPACITY = 100  # req/s


def model():
    return load_model(
        {
            "schema": "branchpoint.model/v1",
            "repo": {"path": "sintetico"},
            "deployment": {
                "api": {"replicas": 1, "vcpu": 1, "workers": 1, "threads_per_worker": 40, "latency_ms": 0},
                "db": {"vcpu": 4, "max_connections": 100, "pool_per_worker": {"pool_size": 10, "max_overflow": 0}},
            },
            "endpoints": [{"id": "GET /x", "weight": 1, "async": True, "api_cpu_ms": 1000 / CAPACITY, "steps": []}],
            "traffic": {"scenarios": {"base": {"rps": CAPACITY}}},
        }
    )


def profile(*segments):
    return TrafficProfile(tuple(TrafficSegment(*s) for s in segments))


def queue_at(run, second):
    return run.series[second - 1].queue["api_cpu"]


def test_queue_grows_over_capacity_and_drains_after():
    """50 req/s por 30 s, 150 req/s por 30 s (sobre la capacidad), y 30 req/s por 60 s."""
    p = profile((30, 0.5, 0.5), (30, 1.5, 1.5), (60, 0.3, 0.3))
    run = simulate(model(), "base", arrivals="uniform", traffic_profile=p, client_timeout_s=None)
    assert run.duration_s == 120 and len(run.series) == 120
    assert queue_at(run, 30) < 5  # bajo la capacidad: casi sin cola
    assert queue_at(run, 60) == pytest.approx(50 * 30, rel=0.05)  # llegan 150/s, salen 100/s durante 30 s
    assert queue_at(run, 120) == 0  # en la bajada salen 70/s más de los que llegan: la cola se vacía
    peak_wait = max(s.latency.p95_ms or 0 for s in run.series)
    assert peak_wait > 10_000  # al final del tramo alto se esperan ~15 s


def test_series_carries_the_target_rate_and_follows_it():
    p = profile((10, 0.2, 0.2), (10, 0.2, 0.8))  # constante y luego rampa de 20 a 80 req/s
    run = simulate(model(), "base", arrivals="uniform", traffic_profile=p)
    assert [s.target_rps for s in run.series[:2]] == [20.0, 20.0]
    assert run.series[-1].target_rps == pytest.approx(20 + 60 * 9.5 / 10, abs=0.01)  # mitad del último segundo
    for s in run.series:
        assert s.arrivals == pytest.approx(s.target_rps, abs=3)
    assert [(seg.start_s, seg.end_s, seg.from_rps, seg.to_rps) for seg in run.traffic_profile] == [
        (0, 10, 20, 20),
        (10, 20, 20, 80),
    ]


def test_constant_profile_is_the_same_as_no_profile():
    """Con llegadas uniformes, un perfil plano en 1× da exactamente el mismo Run que la tasa constante."""
    a = simulate(model(), "base", duration_s=20, arrivals="uniform").to_dict()
    b = simulate(model(), "base", arrivals="uniform", traffic_profile=profile((20, 1, 1))).to_dict()
    for d in (a, b):
        d.pop("elapsed_ms")
        d.pop("traffic_profile")
    assert a == b


def test_poisson_follows_the_profile_on_average():
    """Thinning: el total de llegadas es tasa × duración × multiplicador medio (±5 %)."""
    p = profile((60, 0.2, 1.0), (60, 1.0, 0.2))  # media 0,6
    run = simulate(model(), "base", traffic_profile=p, seed=3)
    assert run.requests == pytest.approx(CAPACITY * 120 * 0.6, rel=0.05)
    first, last = sum(s.arrivals for s in run.series[:10]), sum(s.arrivals for s in run.series[55:65])
    assert last > 3 * first  # el pico (cerca de 60 s) recibe mucho más que el comienzo


def test_zero_segments_and_gaps():
    p = profile((5, 1, 1), (5, 0, 0), (5, 1, 1))  # 5 s sin tráfico en medio
    run = simulate(model(), "base", arrivals="uniform", traffic_profile=p)
    assert all(s.arrivals == 0 for s in run.series[5:10])
    assert sum(s.arrivals for s in run.series[10:]) == pytest.approx(500, abs=2)


def test_preset_pico_shape():
    p = preset("pico", 400)
    assert [s.duration_s for s in p.segments] == [100, 180, 120]
    assert (p.multiplier_at(0), p.multiplier_at(200), p.multiplier_at(399.9)) == pytest.approx((0.35, 1, 0.5), abs=1e-3)
    assert p.peak == 1 and p.duration_s == 400


@pytest.mark.parametrize(
    "build, message",
    [
        (lambda: profile((10, 0, 0)), "no llega nadie"),
        (lambda: profile((0, 1, 1)), "más de 0 s"),
        (lambda: profile((10, -1, 1)), "negativos"),
        (lambda: TrafficProfile(()), "al menos un tramo"),
        (lambda: preset("nada", 60), "Perfil desconocido"),
    ],
)
def test_invalid_profiles(build, message):
    with pytest.raises(ValueError, match=message):
        build()


def test_template_cyberday_with_pico():
    """El template en CyberDay con el perfil pico: la cola de la CPU de la API crece en la meseta."""
    run = simulate(
        load_model(load_sample("full-stack-fastapi-template")), "cyberday", traffic_profile=preset("pico", 120)
    )
    q = [s.queue["api_cpu"] for s in run.series]
    assert run.series[0].target_rps == pytest.approx(262.4 * (0.35 + 0.65 * 0.5 / 30), abs=0.1)
    assert max(q[30:84]) > q[5]
    assert run.traffic_profile[1].from_rps == run.traffic_profile[1].to_rps == pytest.approx(262.4)


# --- JAJ-104: llegadas uniformes que cruzan bordes de tramo ----------------------------------------


@pytest.mark.parametrize("rps", [0.8, 3, 10.5, 37])
@pytest.mark.parametrize("seg_s", [0.25, 1.0, 4.0])
def test_many_flat_segments_are_the_same_as_no_profile(rps, seg_s):
    """BE-12: antes, la cuenta se reiniciaba en cada borde. Con 0,8 req/s y tramos de 1 s no llegaba
    nadie (0 contra 39), y con 10,5 req/s y tramos de 0,25 s llegaban 100 contra 131."""
    n = min(50, int(40 / seg_s))  # hasta 50 tramos (MAX_SEGMENTS)
    with_profile = simulate(model(), "base", rps=rps, arrivals="uniform", traffic_profile=profile(*[(seg_s, 1, 1)] * n))
    without = simulate(model(), "base", rps=rps, duration_s=n * seg_s, arrivals="uniform")
    assert abs(with_profile.requests - without.requests) <= 1


@pytest.mark.parametrize(
    "segments",
    [
        [(30, 0.0, 1.0)],  # rampa desde 0
        [(10, 1.0, 0.2), (10, 0.2, 1.0), (10, 1.0, 1.0)],  # baja, sube y meseta
        [(0.5, 0.3, 1.0)] * 40,  # dientes de sierra cortos
    ],
)
def test_ramps_deliver_rate_times_the_mean_multiplier(segments):
    """Dentro de un tramo la tasa cambia: la siguiente llegada sale de la integral, no de la tasa del
    instante. El total es tasa × duración × multiplicador medio."""
    p = profile(*segments)
    run = simulate(model(), "base", rps=20, arrivals="uniform", traffic_profile=p)
    assert run.requests == pytest.approx(20 * p.duration_s * p.mean, rel=0.01, abs=1)


def test_slope_at():
    p = profile((10, 0.0, 1.0), (5, 1.0, 1.0))
    assert p.slope_at(3) == pytest.approx(0.1) and p.slope_at(12) == 0 and p.slope_at(99) == 0
