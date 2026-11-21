"""Correr una simulación desde la terminal.

python -m app.cli app/samples/full-stack-fastapi-template.model.json --scenario cyberday
python -m app.cli MODELO.json --rps 500 --duration 30 --out run.json
python -m app.cli app/samples/fastapi-realworld-example-app.model.json --cpu-credits burst
python -m app.cli app/samples/full-stack-fastapi-template.model.json --profile pico --duration 300
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.engine import simulate
from app.engine.simulate import ARRIVALS, CPU_CREDITS
from app.models import load_model
from app.models.traffic import PRESETS, preset


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Simula un modelo branchpoint.model/v1 y muestra el resultado.")
    ap.add_argument("model", type=Path, help="JSON del modelo (salida de build_model.py, JAJ-45)")
    ap.add_argument("--scenario", default="cyberday", help="escenario del modelo (por defecto: cyberday)")
    ap.add_argument("--rps", type=float, default=None, help="reemplaza las req/s del escenario")
    ap.add_argument("--duration", type=float, default=60.0, help="segundos simulados (por defecto: 60)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--arrivals", choices=ARRIVALS, default="poisson")
    ap.add_argument("--client-timeout", type=float, default=30.0, help="segundos; 0 = sin timeout")
    ap.add_argument(
        "--cache-hit", type=float, default=None, help="tasa de aciertos (0 a 1) para todas las cachés con on_miss"
    )
    ap.add_argument(
        "--cpu-credits",
        choices=CPU_CREDITS,
        default="sustained",
        help="DB con créditos de CPU (db.t4g.*): sustained = vCPU sostenidos (por defecto), burst = todos los vCPU",
    )
    ap.add_argument(
        "--profile",
        choices=PRESETS,
        default=None,
        help="perfil de tráfico en --duration segundos (pico: subida, meseta y bajada); sin él, tasa constante",
    )
    ap.add_argument("--out", type=Path, default=None, help="guarda el Run completo en JSON")
    a = ap.parse_args(argv)

    # un escenario que no existe, un archivo que no es un modelo o un parámetro fuera de rango: el
    # mensaje en stderr y código 2, como los errores de argparse, en vez de un traceback (JAJ-110)
    try:
        model = load_model(a.model)
        run = simulate(
            model,
            a.scenario,
            seed=a.seed,
            duration_s=a.duration,
            rps=a.rps,
            arrivals=a.arrivals,
            client_timeout_s=a.client_timeout or None,
            cache_hit_ratio=a.cache_hit,
            cpu_credits=a.cpu_credits,
            traffic_profile=preset(a.profile, a.duration) if a.profile else None,
        )
    except OSError as e:
        print(f"error: no se pudo leer {a.model}: {e.strerror or e}", file=sys.stderr)
        return 2
    except KeyError as e:  # load_model: falta un campo; simulate: escenario que no existe (con mensaje)
        detail = e.args[0] if e.args else e
        message = detail if isinstance(detail, str) and " " in detail else f"al modelo le falta el campo {detail!r}"
        print(f"error: {message}", file=sys.stderr)
        return 2
    # incluye un JSON roto, uno que no es un objeto (ej. una lista, JAJ-101) y SimulationTooLarge (JAJ-99)
    except (ValueError, TypeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    lat = run.latency
    fmt = lambda v: "-" if v is None else f"{v:.1f} ms"  # noqa: E731
    print(f"{run.model} · {run.scenario} · {run.rps:g} req/s · {run.duration_s:g} s · semilla {run.seed}")
    print(
        f"requests {run.requests} | ok {run.ok} | errores {sum(run.errors.values())} "
        f"({run.error_rate:.1%}) {run.errors} | en curso al final {run.in_flight}"
    )
    print(
        f"throughput {run.throughput_rps:.1f} req/s | p50 {fmt(lat.p50_ms)} | p95 {fmt(lat.p95_ms)} | "
        f"p99 {fmt(lat.p99_ms)}"
    )
    print("\nrecurso               capacidad   uso    cola máx  cola final  timeouts  espera media")
    for r in run.resources:
        print(
            f"{r.label:<21} {r.capacity:>9} {r.utilization:>6.0%} {r.max_queue:>9} {r.final_queue:>11} "
            f"{r.timeouts:>9} {r.mean_wait_ms:>10.1f} ms"
        )
    if run.cache.hits + run.cache.misses:
        print(f"\ncaché: {run.cache.hits} aciertos, {run.cache.misses} fallos ({run.cache.hit_rate:.0%})")
    for q in run.queues:
        print(
            f"cola {q.name}: {q.enqueued} encolados, {q.processed} procesados, {q.rejected} rechazados, "
            f"{q.final_backlog} esperando al final | trabajo p95 {fmt(q.job_latency.p95_ms)}"
        )
    print(f"\ncuello de botella: {run.bottleneck.message}")
    for w in run.warnings:
        print(f"! {w}")
    print(f"\n(simulado en {run.elapsed_ms:.0f} ms)")
    if a.out:
        a.out.write_text(json.dumps(run.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"-> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
