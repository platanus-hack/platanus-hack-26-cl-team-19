"""Arma el modelo v1 (``branchpoint.model/v1``) de un repo, sin importar su framework (JAJ-45, JAJ-85).

Cruza cuatro fuentes:
  1. El grafo intermedio del repo (endpoints → pasos con forma y ``archivo:línea``), que propone una IA
     (``ai_graph.py``, ADR 0002).
  2. Los archivos de despliegue (``iac.py``, JAJ-60): servicios, réplicas, workers.
  3. El catálogo de números (catalog.json): tiempos calibrados de JAJ-8 y precios de JAJ-11.
  4. Las respuestas del usuario: tráfico, dónde está desplegado, ticket y conversión. Son opcionales:
     lo que falte sale del catálogo como SUPUESTO con ``needs_review`` (el agente lo pide después, JAJ-59).

Uso (desde ``backend/``), con la arquitectura en el formato de ``submit_architecture``:
    python -m app.ingest.build_model arquitectura.json [--answers answers.json] [-o modelo.json]

Cada número del modelo trae `value`, `unit`, `label` (OBSERVADO, CALIBRADO, ESTIMADO, SUPUESTO), `source` y `date`.
El script no simula: solo agrega cotas analíticas simples en `checks` para revisar el modelo.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path

from app.catalog import deploy, load_catalog

RANK = {"OBSERVADO": 0, "CALIBRADO": 1, "ESTIMADO": 2, "SUPUESTO": 3}
SECONDS_MONTH = 30 * 86400


def today() -> str:
    """La fecha de hoy, al momento de armar el número. Antes era una constante del módulo: en un servidor
    con días arriba, los modelos ingeridos salían con la fecha en que arrancó (JAJ-109)."""
    return date.today().isoformat()


# ---------- números con procedencia ----------
def num(value, unit, label, source, *, default=False, **extra) -> dict:
    when = extra.pop("date") if "date" in extra else today()
    out = {"value": value, "unit": unit, "label": label, "source": source, "date": when}
    if label == "SUPUESTO" and default:
        out["needs_review"] = True  # valor por defecto sin respaldo: la UI lo resalta hasta que el usuario lo confirme
    out.update(extra)
    return out


def from_catalog(entry: dict, **over) -> dict:
    return num(
        over.pop("value", entry.get("value")),
        over.pop("unit", entry["unit"]),
        over.pop("label", entry["label"]),
        over.pop("source", entry["source"]),
        default=True,
        date=entry["date"] if "date" in entry else today(),
        **over,
    )


def declared(value, unit, what: str) -> dict:
    return num(value, unit, "SUPUESTO", f"Declarado por el usuario: {what}")


def weakest(*labels: str) -> str:
    return max(labels, key=lambda lab: RANK[lab])


def derived(value, unit, source, *parts: dict) -> dict:
    """Número calculado: hereda la etiqueta más débil de sus entradas."""
    return num(
        value,
        unit,
        weakest(*(p["label"] for p in parts)),
        source,
        default=any(p.get("needs_review") for p in parts),
        derived=True,
    )


# ---------- configuración por defecto ----------
def default_pool(why: str, library: str = "sqlalchemy") -> dict:
    """El pool por defecto de SQLAlchemy, como SUPUESTO por revisar, cuando el repo no dice el suyo."""
    cat = CATALOG["pools"]["sqlalchemy"]
    return {
        "library": library,
        "defined_at": None,
        **{
            k: num(cat[k]["value"], cat[k]["unit"], "SUPUESTO", f"{why}. {cat[k]['source']}", default=True)
            for k in ("pool_size", "max_overflow", "pool_timeout_s")
        },
    }


# ---------- cruce grafo → parámetros ----------
def _entity(detail: str) -> str:
    m = re.search(r"\(([^)]*)\)", detail)
    return m.group(1) if m else ""


def step_for(e: dict, ctx: dict) -> dict:
    """Asigna a un efecto del grafo su costo del catálogo."""
    base = {"kind": e["kind"], "shape": e["shape"], "detail": e["detail"], "at": f"{e['file']}:{e['line']}"}
    if e["kind"] == "db":
        entry = CATALOG["db_shapes"].get(e["shape"]) or CATALOG["db_shapes"]["unknown"]
        if "per_row" in entry:
            ent = _entity(e["detail"])
            rows = ctx["table_rows"].get(ent) or ctx["table_rows_default"]
            t = num(
                round(entry["per_row"] * rows["value"], 4),
                "ms",
                weakest(entry["label"], rows["label"]),
                f"{entry['source']} × {rows['value']} filas de {ent or 'la tabla'} ({rows['source']})",
                default=rows.get("needs_review", False),
            )
        else:
            t = from_catalog(entry)
        step = {**base, "resource": "db_connection", "time": t}
    elif e["kind"] == "cpu":
        step = {**base, "resource": "api_cpu", "time": from_catalog(CATALOG["cpu_steps"][e["shape"]])}
    elif e["kind"] in ("cache", "background"):
        step = {**base, "resource": e["kind"], "time": from_catalog(CATALOG["other_steps"][e["kind"]])}
        if e["kind"] == "background":
            if e.get("queue") in ctx["queues"] and e.get("task"):
                step["queue"] = e["queue"]
            else:
                step["infer_queue"] = False
    else:  # http, sdk, plugin: servicio externo
        declared_ms = ctx["external_ms"].get(e["detail"])
        t = (
            declared(declared_ms, "ms", f"latencia de {e['detail']}")
            if declared_ms is not None
            else from_catalog(CATALOG["other_steps"]["external"])
        )
        step = {**base, "resource": "external", "time": t}
    if e.get("in_loop"):
        n = ctx["n_plus_one"]
        step["repeat"] = num(
            n["value"],
            "×",
            n["label"],
            f"N+1: se ejecuta una vez por iteración ({n['source']})",
            default=n.get("needs_review", False),
        )
    step["via"] = e["via"]
    if e.get("service"):
        step["service"] = e["service"]
    if e.get("origin"):
        # Paso propuesto por la IA (JAJ-85): el costo sale del catálogo, pero la clasificación no la
        # verificó nadie más, así que el número no puede ser más fuerte que ESTIMADO.
        t = step["time"]
        step["time"] = {
            **t,
            "label": weakest(t["label"], "ESTIMADO"),
            "source": f"{t['source']}. {e['origin']['source']}",
        }
        step["origin"] = e["origin"]
    return step


def _ms(step: dict) -> float:
    v = step["time"]["value"] or 0.0
    if "on_miss" in step:
        v += (1 - (step["hit_ratio"]["value"] or 0)) * (v + sum(_ms(query) for query in step["on_miss"]))
    return v * (step["repeat"]["value"] if "repeat" in step else 1)


def pick_branches(steps: list[dict], depth: int = 0) -> tuple[list[dict], list[dict]]:
    """En un if/else con efectos en las dos ramas, se queda con la rama más cara (peor caso) y guarda la otra."""
    kept, dropped, groups = [], [], {}
    for s in steps:
        br = s["branch"]
        if len(br) <= depth:
            kept.append(s)
        else:
            groups.setdefault(br[depth][0], {}).setdefault(br[depth][1], []).append(s)
    for sides in groups.values():
        res = {side: pick_branches(ss, depth + 1) for side, ss in sides.items()}
        best = max(res, key=lambda side: sum(_ms(x) for x in res[side][0]))
        for side, (k, d) in res.items():
            if len(res) == 1 or side == best:
                kept += k
                dropped += d
            else:
                dropped += k + d
    return kept, dropped


def effect_steps(effects: list[dict], ctx: dict) -> list[dict]:
    steps = [{**step_for(e, ctx), "branch": e["branch"]} for e in effects]
    moved: set[int] = set()
    for lookup, step in zip(effects, steps, strict=True):
        if "cache_miss" not in lookup:
            continue
        guard, fill_line = lookup["cache_miss"]
        miss_branch = [*lookup["branch"], [guard, "cache_miss"]]
        region = [i for i, e in enumerate(effects) if e["branch"][: len(miss_branch)] == miss_branch]
        fills = [
            i
            for i in region
            if effects[i]["kind"] == "cache"
            and effects[i]["line"] == fill_line
            and effects[i]["file"] == lookup["file"]
        ]
        if len(fills) != 1 or moved.intersection(region):
            continue
        queries = [i for i in region if i != fills[0]]
        if not queries or not all(effects[i]["kind"] == "db" and effects[i]["op"] == "read" for i in queries):
            continue
        # El motor ya simula el SET después de on_miss: el set que guarda la clave no se cuenta aparte.
        on_miss = [{**steps[i], "branch": steps[i]["branch"][len(miss_branch) :]} for i in queries]
        selected, _ = pick_branches(on_miss)
        order = {id(query): i for i, query in enumerate(on_miss)}
        selected.sort(key=lambda query: order[id(query)])
        for query in selected:
            query.pop("branch")
        at = step["at"]
        ratio = ctx["cache_hit_ratio"].get(at)
        what = f"tasa de aciertos de la caché en {at}"
        if ratio is None:
            step["hit_ratio"] = num(None, "fracción", "SUPUESTO", f"Falta la {what}", default=True)
        else:
            if type(ratio) not in (int, float) or not 0 <= ratio <= 1:
                raise ValueError(f"La {what} debe estar entre 0 y 1")
            step["hit_ratio"] = declared(ratio, "fracción", what)
        step["on_miss"] = selected
        moved.update(region)
    return [step for i, step in enumerate(steps) if i not in moved]


def _add_cache_questions(steps: list[dict], questions: dict[str, str]) -> None:
    """Pregunta por las cachés que quedaron en los pasos de la simulación."""
    for step in steps:
        if step.get("hit_ratio", {}).get("needs_review"):
            at = step["at"]
            questions[f"overrides.cache_hit_ratio.{at}"] = (
                f"¿Cuál es la tasa de aciertos de la caché en {at}, como fracción entre 0 y 1?"
            )


def _mean_cache_reads(steps: list[dict]) -> list[dict]:
    reads = []
    for cache in steps:
        if "on_miss" not in cache:
            continue
        ratio = cache["hit_ratio"]
        for query in cache["on_miss"]:
            time = query["time"]
            mean_ms = (time["value"] or 0) * (1 - (ratio["value"] or 0))
            mean = derived(mean_ms, "ms", "Tiempo de la consulta × fracción de fallos de caché", time, ratio)
            reads.append({**query, "time": mean})
    return reads


def build_endpoint(ep: dict, ctx: dict) -> dict:
    steps = effect_steps(ep["effects"], ctx)
    kept, dropped = pick_branches(steps)
    _add_cache_questions(kept, ctx["questions"])
    order = {id(s): i for i, s in enumerate(steps)}
    kept.sort(key=lambda s: order[id(s)])
    db = [s for s in kept if s["resource"] == "db_connection"]
    cpu = [s for s in kept if s["resource"] == "api_cpu"]
    # La sesión es por request: la conexión se toma en la primera query y se suelta al cerrar la sesión.
    # La CPU pesada cuenta dentro de la conexión si corre en una dependencia o en una función que también consulta la DB.
    db_funcs = {f for s in db for f in s["via"][1:]}
    dep_db = any(s["via"][0] != ep["handler"] for s in db)
    cpu_in_hold = [s for s in cpu if db and (dep_db or db_funcs & set(s["via"][1:]))]
    db += _mean_cache_reads(kept)
    # La CPU propia del framework depende de si el endpoint bloquea su proceso o no (JAJ-46). El catálogo
    # dice en qué framework se midió: en otro, el valor es un supuesto por revisar (JAJ-85).
    entry = CATALOG["api"]["cpu_ms" if ep.get("async") else "cpu_ms_sync"]
    base_cpu = from_catalog(entry)
    framework = (ep.get("origin") or {}).get("framework")
    if framework and entry.get("framework") and framework != entry["framework"]:
        base_cpu = {
            **base_cpu,
            "label": "SUPUESTO",
            "source": f"{base_cpu['source']}. Medido en {entry['framework']}; el repo usa {framework}",
        }
    parts_hold = [s["time"] for s in db + cpu_in_hold] + [s["repeat"] for s in db if "repeat" in s]
    hold = (
        derived(
            round(sum(_ms(s) for s in db + cpu_in_hold), 4),
            "ms",
            "Suma de las queries (y la CPU pesada que corre con la conexión tomada)",
            *parts_hold,
        )
        if db
        else num(0.0, "ms", "OBSERVADO", "El endpoint no usa la DB")
    )
    api_cpu = derived(
        round(base_cpu["value"] + sum(_ms(s) for s in cpu), 4),
        "ms",
        "CPU base del framework + CPU pesada del endpoint",
        base_cpu,
        *[s["time"] for s in cpu],
    )
    ext = [s for s in kept if s["resource"] == "external"]
    for s in kept + dropped:
        s.pop("branch", None)
    out = {
        "id": f"{ep['method']} {ep['path']}",
        "method": ep["method"],
        "path": ep["path"],
        "handler": ep["handler"],
        "at": f"{ep['file']}:{ep['line']}",
        "async": ep.get("async", False),
        "steps": kept,
        "alternatives": dropped,
        "db_hold_ms": hold,
        "api_cpu_ms": api_cpu,
        "external_ms": derived(sum(_ms(s) for s in ext), "ms", "Suma de llamadas externas", *[s["time"] for s in ext])
        if ext
        else None,
        "risks": ep["risks"],
    }
    if ep.get("origin"):
        out["origin"] = ep["origin"]
    return out


def build_queues(graph: dict, iac: dict, answers: dict, ctx: dict) -> dict:
    tasks_by_queue: dict[str, set[str | None]] = {}
    for ep in graph["endpoints"]:
        for effect in ep["effects"]:
            if name := effect.get("queue"):
                tasks_by_queue.setdefault(name, set()).add(effect.get("task"))

    queues = {}
    for name, tasks in sorted(tasks_by_queue.items()):
        # El motor ejecuta un solo perfil de trabajo por cola. Si se mezclan tareas no lo adivinamos.
        if len(tasks) != 1 or None in tasks:
            continue
        task = next(iter(tasks))
        effects = graph.get("jobs", {}).get(task, [])
        if not effects or any(e["kind"] == "background" for e in effects):
            continue
        candidates = effect_steps(effects, ctx)
        steps, _ = pick_branches(candidates)
        _add_cache_questions(steps, ctx["questions"])
        order = {id(step): i for i, step in enumerate(candidates)}
        steps.sort(key=lambda step: order[id(step)])
        for step in steps:
            step.pop("branch")
        config = answers.get(name, {})
        services = [s for s in iac["services"] if s.get("queue") == name]
        observed_workers = None
        if len(services) == 1 and "workers" in services[0]:
            service = services[0]
            observed_workers = service["workers"]
            if replicas := service.get("replicas"):
                observed_workers = derived(
                    observed_workers["value"] * replicas["value"],
                    "workers",
                    f"{observed_workers['source']} × {replicas['source']}",
                    observed_workers,
                    replicas,
                )
        params = {}
        for field, unit, default, question in (
            ("workers", "workers", 1, f"¿Cuántos trabajos procesa en paralelo la cola {name}?"),
            ("max_length", "trabajos", None, f"¿Cuántos trabajos pueden esperar en la cola {name}?"),
        ):
            if field in config:
                value = config[field]
                if (value is not None or field != "max_length") and (type(value) is not int or value < 1):
                    raise ValueError(f"deployment.queues.{name}.{field} debe ser un entero positivo")
                params[field] = declared(value, unit, f"{field} de la cola {name}")
            elif field == "workers" and observed_workers and observed_workers["value"] >= 1:
                params[field] = observed_workers
            else:
                source = f"El repo no declara {field} para la cola {name}"
                params[field] = num(default, unit, "SUPUESTO", source, default=True)
                ctx["questions"][f"deployment.queues.{name}.{field}"] = question
        queues[name] = {**params, "job_steps": steps}
    return queues


def endpoint_weights(endpoints: list[dict], overrides: dict) -> None:
    if overrides:
        total = sum(overrides.values())
        for ep in endpoints:
            w = overrides.get(ep["id"], 0) / total
            ep["weight"] = declared(round(w, 4), "fracción", "reparto del tráfico entre endpoints")
        return
    share = CATALOG["traffic"]["read_share"]
    reads = [e for e in endpoints if e["method"] == "GET"]
    writes = [e for e in endpoints if e["method"] != "GET"]
    r_share = share["value"] if reads and writes else (1.0 if reads else 0.0)
    for group, g_share in ((reads, r_share), (writes, 1 - r_share)):
        for ep in group:
            ep["weight"] = from_catalog(share, value=round(g_share / len(group), 4), unit="fracción")


# ---------- respuestas del usuario: tráfico, despliegue y negocio ----------
def traffic_model(ans: dict) -> dict:
    t = ans.get("traffic", {})
    tr = CATALOG["traffic"]
    k_hour = from_catalog(tr["k_hour"])
    if t.get("mode") == "rps":
        peak = declared(t["peak_rps"], "req/s", "requests por segundo en la hora pico")
        rps_session = num(
            tr["profiles"]["medio"]["requests_per_session"],
            "requests/sesión",
            "SUPUESTO",
            "Perfil medio de uso de una app web, sin dato del usuario",
            default=True,
        )
        inputs = {"peak_rps": peak}
    else:
        prof_name = t.get("profile", "medio")
        prof = tr["profiles"][prof_name]
        if "mau" in t:
            mau = declared(t["mau"], "usuarios/mes", "usuarios activos al mes")
        else:  # el usuario todavía no dijo su tráfico (JAJ-57): supuesto por revisar
            mau = from_catalog(tr["mau_default"])
        profile_src = "Declarado por el usuario" if "profile" in t else "Perfil por defecto, sin dato del usuario"
        profile = num(
            prof_name,
            "perfil",
            "SUPUESTO",
            f"{profile_src}. {tr['_source']}",
            default="profile" not in t,
            sessions_per_month=prof["sessions_per_month"],
            requests_per_session=prof["requests_per_session"],
        )
        rps_session = num(
            prof["requests_per_session"], "requests/sesión", "SUPUESTO", f"Perfil {prof_name} de uso de una app web"
        )
        avg = mau["value"] * prof["sessions_per_month"] * prof["requests_per_session"] / SECONDS_MONTH
        peak = derived(
            round(avg * k_hour["value"], 2),
            "req/s",
            "usuarios/mes × sesiones/mes × requests/sesión / segundos del mes × K_hora",
            mau,
            profile,
            k_hour,
        )
        inputs = {"mau": mau, "profile": profile, "k_hour": k_hour, "peak_rps": peak}
    scenarios = {}
    for name, sc in tr["scenarios"].items():
        mult = num(sc["multiplier"], "×", sc["label"], sc["source"], default=True)
        scenarios[name] = {
            "multiplier": mult,
            "rps": derived(round(peak["value"] * sc["multiplier"], 2), "req/s", "pico × multiplicador", peak, mult),
        }
    return {**inputs, "requests_per_session": rps_session, "scenarios": scenarios}


def _assumed(field: dict, why: str) -> dict:
    """Un número del perfil de un plan que nadie confirmó: queda SUPUESTO por revisar."""
    return {**field, "label": "SUPUESTO", "needs_review": True, "source": f"{field['source']}. {why}"}


def _db_choice(d: dict, seen: dict, warnings: list[str]) -> tuple[str, str, str, bool]:
    """(proveedor, plan, por qué, si el plan es supuesto) de la DB: el usuario, luego el repo, luego local."""
    if "db" in d:
        return d["db"]["provider"], d["db"]["plan"], "declarado por el usuario", False
    providers = deploy.db_providers(CATALOG)
    plan_seen, provider_seen = seen.get("db.plan"), seen.get("db.provider")
    if plan_seen:
        name = str(plan_seen["value"])
        owners = [p for p, plans in providers.items() if name in plans]
        if provider_seen and provider_seen["value"] in owners:
            owners = [provider_seen["value"]]
        if len(owners) == 1:
            return owners[0], name, f"{plan_seen['source']} ({plan_seen['at']})", False
        warnings.append(f"El plan de la DB del repo ({name}, {plan_seen['at']}) no está en el catálogo.")
    if provider_seen:
        provider = provider_seen["value"]
        smallest = providers[provider][0]
        why = (
            f"{provider_seen['source']} ({provider_seen['at']}). El repo no dice el plan: se asume el más "
            f"chico de {provider}, por revisar"
        )
        return provider, smallest, why, True
    return "local", "docker", "valor por defecto: ni el usuario ni el repo dicen dónde está la DB", False


def _service_technology(s: dict) -> dict | None:
    """El bloque ``technology`` de un servicio (JAJ-87): de la IaC es OBSERVADO; de la IA, ESTIMADO."""
    if not s.get("engine"):
        return None
    name = ENGINE_NAMES.get(str(s["engine"]).lower(), s["engine"])
    if s.get("origin"):
        return deploy.technology(name, None, "ESTIMADO", f"Propuesto por la IA en {s.get('at')}", at=s.get("at"))
    what = f"imagen {s['image']}" if s.get("image") else f"motor {s['engine']}"
    return deploy.technology(name, s.get("version"), "OBSERVADO", f"{what} en {s['at']}", at=s["at"])


def _db_technology(db: dict, services: list[dict]) -> dict | None:
    """El motor de la DB (JAJ-87): la imagen de la IaC, si no el proveedor, si no lo que propuso la IA."""
    dbs = [s for s in services if s.get("role") == "db" and s.get("engine")]
    for s in dbs:
        if not s.get("origin"):
            return _service_technology(s)
    if "technology" in db:
        return db["technology"]
    return _service_technology(dbs[0]) if dbs else None


ENGINE_NAMES = {
    "postgres": "PostgreSQL",
    "postgis": "PostgreSQL (PostGIS)",
    "timescale": "PostgreSQL (TimescaleDB)",
    "mysql": "MySQL",
    "mariadb": "MariaDB",
    "mongo": "MongoDB",
    "redis": "Redis",
    "valkey": "Valkey",
    "memcached": "Memcached",
    "rabbitmq": "RabbitMQ",
    "kafka": "Kafka",
}


def _app_plan(provider: str, a: dict, seen: dict, vcpu: dict, warnings: list[str]) -> tuple[str | None, str, bool]:
    """(plan, por qué, si es supuesto) de la API en Fly o Render; ``None`` en Fargate y local."""
    plans = deploy.app_providers(CATALOG)[provider]
    if not plans:
        return None, "", False
    if "plan" in a:
        return a["plan"], "declarado por el usuario", False
    if seen.get("api.plan"):
        name = (
            re.sub(r"[\s-]+", "_", str(seen["api.plan"]["value"]).lower())
            if provider == "render"
            else str(seen["api.plan"]["value"])
        )
        if name in plans:
            return name, f"{seen['api.plan']['source']} ({seen['api.plan']['at']})", False
        warnings.append(
            f"El plan de la API del repo ({name}, {seen['api.plan']['at']}) no está en el catálogo de {provider}: se "
            "simula con un plan de CPU dedicada parecido, por revisar. Una máquina shared rinde menos con carga sostenida."
        )
    # Sin plan dicho: el que calza con los vCPU, o el más chico. Por revisar.
    fit = next(
        (p for p in plans if CATALOG["app_plans"][provider]["plans"][p]["vcpu"] >= (vcpu["value"] or 0)), plans[0]
    )
    return fit, f"el repo no dice el plan de {provider}: se asume {fit}, por revisar", True


def deployment_model(ans: dict, workers: dict, pool: dict, iac: dict) -> dict:
    d = ans.get("deployment", {})
    seen = iac["observed"]
    warnings = iac["warnings"]
    provider, plan_name, why, assumed = _db_choice(d, seen, warnings)
    db = {**deploy.db_profile(provider, plan_name, why, CATALOG), "pool_per_worker": pool}
    if assumed:
        for key in ("vcpu", "ram_gb", "max_connections", "usd_month"):
            db[key] = _assumed(db[key], "Plan supuesto")
    if (tech := _db_technology(db, iac["services"])) is not None:
        db["technology"] = tech
    else:
        db.pop("technology", None)
    if "db.provider" in seen and provider == seen["db.provider"]["value"]:
        db["provider_seen_at"] = seen["db.provider"]["at"]
    # Cada número: la respuesta del usuario manda; si no, lo que dice el repo (JAJ-60); si no, el valor por defecto
    a = d.get("api", {})
    defaults = {"replicas": 1, "vcpu": 1, "memory_gb": 2}
    api_vals = {}
    for key, unit, what in (
        ("replicas", "réplicas", "réplicas de la API"),
        ("vcpu", "vCPU", "vCPU por réplica"),
        ("memory_gb", "GB", "memoria por réplica"),
    ):
        if key in a:
            api_vals[key] = declared(a[key], unit, what)
        elif f"api.{key}" in seen:
            api_vals[key] = seen[f"api.{key}"]
        else:
            api_vals[key] = num(
                defaults[key],
                unit,
                "SUPUESTO",
                f"Valor por defecto: ni el usuario ni el repo dicen {what}",
                default=True,
            )
    if "provider" in a:
        api_provider, provider_why = a["provider"], "declarado por el usuario"
    elif "api.provider" in seen and deploy.app_provider_from_target(seen["api.provider"]["value"]):
        api_provider = deploy.app_provider_from_target(seen["api.provider"]["value"])
        provider_why = f"{seen['api.provider']['source']} ({seen['api.provider']['at']})"
    else:
        if "api.provider" in seen:
            warnings.append(
                f"La API se despliega en {seen['api.provider']['value']} ({seen['api.provider']['at']}), que no "
                "está en el catálogo: se simula como local."
            )
        api_provider, provider_why = "local", "valor por defecto"
    plan, plan_why, plan_assumed = _app_plan(api_provider, a, seen, api_vals["vcpu"], warnings)
    profile = deploy.app_profile(
        api_provider,
        plan,
        api_vals["replicas"],
        api_vals["vcpu"],
        api_vals["memory_gb"],
        plan_why or provider_why,
        CATALOG,
    )
    if plan_assumed:
        for key in ("vcpu", "memory_gb", "usd_month"):
            profile[key] = _assumed(profile[key], "Plan supuesto")
    api = {
        "provider": api_provider,
        "replicas": api_vals["replicas"],
        "vcpu": profile.get("vcpu", api_vals["vcpu"]),
        "memory_gb": profile.get("memory_gb", api_vals["memory_gb"]),
        "workers": workers,
        "threads_per_worker": from_catalog(CATALOG["api"]["threads_per_worker"]),
        "latency_ms": from_catalog(CATALOG["api"]["latency_ms"]),
        "usd_month": profile["usd_month"],
        "cpu_core_factor": profile["cpu_core_factor"],
    }
    if plan:
        api["plan"] = plan
    out = {"api": api, "db": db}
    frontend = _frontend(d, seen)
    if frontend:
        out["frontend"] = frontend
    # Lo que el agente tiene que preguntar (JAJ-59): lo que no dicen ni el repo ni las respuestas
    answered = {f"api.{k}" for k in a} | ({"db.plan"} if "db" in d else set())
    if not assumed and "db.plan" not in answered and provider != "local":
        answered.add("db.plan")
    services = [{**svc, "technology": tech} if (tech := _service_technology(svc)) else svc for svc in iac["services"]]
    return {
        **out,
        "services": services,
        "iac": {
            "files": iac["files"],
            "deploy_targets": iac["deploy_targets"],
            "warnings": warnings,
            "missing": [m for m in iac["missing"] if m["field"] not in answered],
        },
    }


def _frontend(d: dict, seen: dict) -> dict | None:
    """Dónde se sirve el frontend, si el usuario o el repo lo dicen. No se inventa uno."""
    if "frontend" in d:
        f = d["frontend"]
        return deploy.frontend_profile(f["provider"], f["plan"], "declarado por el usuario", CATALOG)
    target = seen.get("frontend.provider")
    provider = deploy.frontend_provider_from_target(target["value"]) if target else None
    if provider is None:
        return None
    plan = deploy.frontend_providers(CATALOG)[provider][0]
    out = deploy.frontend_profile(
        provider, plan, f"{target['source']} ({target['at']}). Se asume el plan {plan}, por revisar", CATALOG
    )
    out["usd_month"] = _assumed(out["usd_month"], "Plan supuesto")
    return out


def business_model(ans: dict) -> dict:
    b = ans.get("business", {})
    cat = CATALOG["business_defaults"]
    return {
        "ticket_usd": declared(b["ticket_usd"], "US$", "ticket promedio")
        if "ticket_usd" in b
        else from_catalog(cat["ticket_usd"]),
        "conversion": declared(b["conversion"], "fracción", "conversión")
        if "conversion" in b
        else from_catalog(cat["conversion"]),
    }


# ---------- cotas analíticas (no reemplazan la simulación) ----------
def checks(model: dict) -> dict:
    api, db = model["deployment"]["api"], model["deployment"]["db"]
    pool = db["pool_per_worker"]
    eps = model["endpoints"]
    per_worker = (pool["pool_size"]["value"] or 0) + (pool["max_overflow"]["value"] or 0)
    conns = derived(
        api["replicas"]["value"] * api["workers"]["value"] * per_worker,
        "conexiones",
        "réplicas × workers × (pool_size + max_overflow): cada proceso tiene su propio pool",
        api["replicas"],
        api["workers"],
        pool["pool_size"],
        pool["max_overflow"],
    )
    usable = min(conns["value"], db["max_connections"]["value"])
    # Los tiempos del catálogo son de 1 núcleo del laptop: en la nube la CPU de la API y las queries tardan
    # cpu_core_factor veces más (JAJ-46). La conexión tomada suma queries (DB) y CPU pesada (API).
    f_api, f_db = api["cpu_core_factor"], db["cpu_core_factor"]
    db_ms_ep = {id(e): sum(_ms(s) for s in e["steps"] if s["resource"] == "db_connection") for e in eps}
    hold = sum(
        e["weight"]["value"]
        * (db_ms_ep[id(e)] * f_db["value"] + (e["db_hold_ms"]["value"] - db_ms_ep[id(e)]) * f_api["value"])
        for e in eps
    )
    cpu = sum(e["weight"]["value"] * e["api_cpu_ms"]["value"] for e in eps) * f_api["value"]
    db_ms = sum(e["weight"]["value"] * db_ms_ep[id(e)] for e in eps) * f_db["value"]
    lab = [x for e in eps for x in (e["weight"], e["db_hold_ms"], e["api_cpu_ms"])]
    mean_hold = derived(
        round(hold, 4),
        "ms",
        "promedio ponderado por el tráfico de db_hold_ms, en la nube (× cpu_core_factor)",
        *lab,
        f_api,
        f_db,
    )
    mean_cpu = derived(
        round(cpu, 4),
        "ms",
        "promedio ponderado por el tráfico de api_cpu_ms, en la nube (× cpu_core_factor)",
        *lab,
        f_api,
    )
    cores = min(api["workers"]["value"], api["vcpu"]["value"]) * api["replicas"]["value"]
    db_vcpu = db["cpu_credits"]["sustained_vcpu"] if "cpu_credits" in db else db["vcpu"]
    caps = {
        "pool": derived(
            round(usable * 1000 / hold, 1) if hold else None,
            "req/s",
            "conexiones usables / tiempo promedio con la conexión tomada (ley de Little)",
            conns,
            mean_hold,
            db["max_connections"],
        ),
        "db_cpu": derived(
            round(db_vcpu["value"] * 1000 / db_ms, 1) if db_ms else None,
            "req/s",
            "vCPU de la DB (la base sostenida si tiene créditos) / tiempo de queries por request en la "
            "nube (los tiempos calibrados son de 1 núcleo del laptop × cpu_core_factor)",
            db_vcpu,
            mean_hold,
            f_db,
        ),
        "api_cpu": derived(
            round(cores * 1000 / cpu, 1),
            "req/s",
            "núcleos usables (mín. entre workers y vCPU, por réplica) / CPU por request en la nube",
            api["workers"],
            api["vcpu"],
            api["replicas"],
            mean_cpu,
        ),
    }
    t = model["traffic"]
    biz = model["business"]
    scen = {}
    for name, sc in t["scenarios"].items():
        rps = sc["rps"]["value"]
        valid = {k: v for k, v in caps.items() if v["value"]}
        # sin ninguna capacidad con valor (ej. sin consultas y sin CPU), no hay cuello que nombrar (JAJ-108)
        bottleneck = min(valid, key=lambda k: valid[k]["value"]) if valid else None
        sessions_h = rps * 3600 / t["requests_per_session"]["value"]
        at_stake = derived(
            round(sessions_h * biz["conversion"]["value"] * biz["ticket_usd"]["value"], 0),
            "US$/hora",
            "sesiones/hora × conversión × ticket: ventas en juego por hora si el sistema se cae",
            sc["rps"],
            t["requests_per_session"],
            biz["conversion"],
            biz["ticket_usd"],
        )
        scen[name] = {
            "rps": rps,
            "utilization": {k: round(rps / v["value"], 3) for k, v in valid.items()},
            "bottleneck": bottleneck,
            "sales_at_stake_per_hour": at_stake,
        }
    status = (
        "excede"
        if conns["value"] > db["max_connections"]["value"]
        else "al límite"
        if conns["value"] == db["max_connections"]["value"]
        else "ok"
    )
    return {
        "_doc": "Cotas analíticas simples para revisar el modelo. No reemplazan la simulación.",
        "connections": {"app_max": conns, "db_max": db["max_connections"], "status": status},
        "mean_db_hold_ms": mean_hold,
        "mean_api_cpu_ms": mean_cpu,
        "capacity": caps,
        "scenarios": scen,
    }


def collect_assumptions(node, path="") -> list[dict]:
    """Números SUPUESTO de origen (no los calculados a partir de ellos), para resaltarlos en la UI."""
    out = []
    if isinstance(node, dict):
        if node.get("label") == "SUPUESTO" and "value" in node and not node.get("derived"):
            out.append(
                {
                    "path": path,
                    "value": node["value"],
                    "unit": node["unit"],
                    "source": node["source"],
                    "needs_review": node.get("needs_review", False),
                }
            )
        for k, v in node.items():
            out += collect_assumptions(v, f"{path}.{k}" if path else k)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out += collect_assumptions(v, f"{path}[{i}]")
    return out


class NoEndpoints(ValueError):
    """La IA no encontró endpoints que modelar en el repo."""


NO_ENDPOINTS = (
    "No encontramos endpoints HTTP en ese repo y esa rama. Si el backend está en otra rama o en otro repo, "
    "analiza esa; si es un monorepo, revisa que la rama tenga el código del servidor."
)


def endpoint_context(answers: dict) -> dict:
    """Lo que necesita ``build_endpoint`` para ponerle números a los pasos: respuestas o catálogo."""
    ov = answers.get("overrides", {})
    return {
        "table_rows": {k: declared(v, "filas", f"filas de {k}") for k, v in ov.get("table_rows", {}).items()},
        "table_rows_default": from_catalog(CATALOG["table_rows_default"]),
        "n_plus_one": declared(ov["n_plus_one_list"], "iteraciones", "largo de las listas con N+1")
        if "n_plus_one_list" in ov
        else from_catalog(CATALOG["n_plus_one_list_default"]),
        "external_ms": ov.get("external_ms", {}),
        "cache_hit_ratio": ov.get("cache_hit_ratio", {}),
        "questions": {},
        "queues": {},
    }


def summarize_assumptions(model: dict) -> dict:
    found = collect_assumptions({k: v for k, v in model.items() if k != "checks"})
    by_source: dict[str, dict] = {}
    for a in found:
        g = by_source.setdefault(
            a["source"],
            {"source": a["source"], "count": 0, "needs_review": a["needs_review"], "example_path": a["path"]},
        )
        g["count"] += 1
    return {
        "total": len(found),
        "by_source": sorted(by_source.values(), key=lambda g: -g["count"]),
        "items": found,
    }


def build_from_graph(graph: dict, repo_name: str, answers: dict, *, iac: dict, workers: dict, pool: dict) -> dict:
    """El modelo ``branchpoint.model/v1`` desde el grafo intermedio, sin importar de dónde salió el grafo.

    El grafo son endpoints → efectos con forma y ``archivo:línea``, y opcionalmente ``jobs`` de colas. Lo
    arma ``ai_graph.to_graph`` desde lo que propone la IA (ADR 0002).
    Los números salen siempre del catálogo, de las respuestas o de la IaC (ADR 0001)."""
    ctx = endpoint_context(answers)
    queues = build_queues(graph, iac, answers.get("deployment", {}).get("queues", {}), ctx)
    ctx["queues"] = queues
    endpoints = [build_endpoint(ep, ctx) for ep in graph["endpoints"]]
    endpoint_weights(endpoints, answers.get("overrides", {}).get("endpoint_weights", {}))
    deployment = deployment_model(answers, workers, pool, iac)
    if queues:
        deployment["queues"] = queues
    deployment["iac"]["missing"].extend(
        {"field": field, "question": question} for field, question in ctx["questions"].items()
    )
    model = {
        "schema": "branchpoint.model/v1",
        "repo": {
            "path": repo_name,
            "extracted_at": today(),
            "stats": {k: v for k, v in graph["stats"].items() if not k.startswith("seconds")},
        },
        "deployment": deployment,
        "traffic": traffic_model(answers),
        "business": business_model(answers),
        "endpoints": endpoints,
    }
    if graph.get("source"):
        model["repo"]["source"] = graph["source"]
    model["checks"] = checks(model)
    model["assumptions"] = summarize_assumptions(model)
    return model


CATALOG = load_catalog()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("architecture", type=Path, help="JSON con el formato de submit_architecture")
    ap.add_argument("--answers", type=Path, help="respuestas del usuario; sin ellas, supuestos del catálogo")
    ap.add_argument("-o", "--out", type=Path)
    args = ap.parse_args()
    answers = json.loads(args.answers.read_text(encoding="utf-8")) if args.answers else {}
    from app.ingest.ai_graph import ArchitectureSubmission, build_from_ai  # importa este módulo

    sub = ArchitectureSubmission.model_validate_json(args.architecture.read_text(encoding="utf-8"))
    model = build_from_ai(sub, answers)
    txt = json.dumps(model, indent=2, ensure_ascii=False)
    if args.out:
        args.out.write_text(txt + "\n", encoding="utf-8")
    c = model["checks"]
    print(
        json.dumps(
            {
                "endpoints": len(model["endpoints"]),
                "assumptions": model["assumptions"]["total"],
                "assumption_sources": len(model["assumptions"]["by_source"]),
                "connections": {k: v["value"] if isinstance(v, dict) else v for k, v in c["connections"].items()},
                "capacity_rps": {k: v["value"] for k, v in c["capacity"].items()},
                "scenarios": {
                    k: {"rps": v["rps"], "bottleneck": v["bottleneck"], "utilization": v["utilization"]}
                    for k, v in c["scenarios"].items()
                },
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
