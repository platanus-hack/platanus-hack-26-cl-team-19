"""``TrafficProfile``: el perfil de tráfico en el tiempo (JAJ-71), probado sin el motor (JAJ-110)."""

from __future__ import annotations

import pytest

from app.models.traffic import MAX_SEGMENTS, TrafficProfile, TrafficSegment, preset


def profile(*segments):
    return TrafficProfile(tuple(TrafficSegment(*s) for s in segments))


def test_duration_peak_and_mean():
    p = profile((10, 0.0, 1.0), (20, 1.0, 1.0), (10, 1.0, 0.5))
    assert p.duration_s == 40 and p.peak == 1.0
    # área: 10·0,5 + 20·1 + 10·0,75 = 32,5 en 40 s
    assert p.mean == pytest.approx(32.5 / 40)


def test_multiplier_is_linear_inside_a_segment_and_zero_after_the_end():
    p = profile((10, 0.0, 1.0), (10, 1.0, 0.5))
    assert p.multiplier_at(0) == 0 and p.multiplier_at(5) == pytest.approx(0.5)
    assert p.multiplier_at(10) == 1.0 and p.multiplier_at(15) == pytest.approx(0.75)
    assert p.multiplier_at(20) == 0 and p.multiplier_at(99) == 0


def test_next_change_is_the_next_segment_border():
    p = profile((10, 1, 1), (5, 2, 2))
    assert p.next_change(0) == 10 and p.next_change(10) == 15 and p.next_change(99) == 15


def test_from_dicts():
    p = TrafficProfile.from_dicts([{"duration_s": 60, "from_multiplier": 0.35, "to_multiplier": 1}])
    assert p.segments == (TrafficSegment(60.0, 0.35, 1.0),)


def test_preset_pico_scales_to_the_duration():
    """25 % de subida de 0,35 a 1, 45 % de meseta y 30 % de bajada hasta 0,5."""
    p = preset("pico", 200)
    assert [s.duration_s for s in p.segments] == pytest.approx([50, 90, 60])
    assert (p.segments[0].from_multiplier, p.segments[-1].to_multiplier) == (0.35, 0.5)
    assert p.duration_s == pytest.approx(200)


@pytest.mark.parametrize(
    "build, match",
    [
        (lambda: TrafficSegment(0, 1, 1), "más de 0 s"),
        (lambda: TrafficSegment(10, -1, 1), "negativos"),
        (lambda: TrafficProfile(()), "al menos un tramo"),
        (lambda: profile((10, 0, 0)), "no llega nadie"),
        (lambda: profile(*[(1, 1, 1)] * (MAX_SEGMENTS + 1)), f"hasta {MAX_SEGMENTS} tramos"),
        (lambda: preset("valle", 60), "Perfil desconocido"),
        (lambda: preset("pico", 0), "mayor que 0"),
    ],
)
def test_invalid_profiles(build, match):
    with pytest.raises(ValueError, match=match):
        build()
