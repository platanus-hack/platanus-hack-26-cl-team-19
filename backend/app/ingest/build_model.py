"""Arma el modelo v1 (branchpoint.model/v1) de un repo FastAPI (JAJ-45, movido de spikes/ en JAJ-57).

Cruza tres fuentes:
  1. El grafo del repo (extractor de JAJ-7), más la configuración que se lee del repo (workers, pool).
  2. El catálogo de números (catalog.json): tiempos calibrados de JAJ-8 y precios de JAJ-11.
  3. Las 3 respuestas del usuario: tráfico, dónde está desplegado, ticket y conversión. Son opcionales:
     lo que falte sale del catálogo como SUPUESTO con ``needs_review`` (el agente lo pide después, JAJ-59).

Uso (desde ``backend/``):
    python -m app.ingest.build_model <ruta-al-repo> [--answers answers.json] [-o modelo.json]

Cada número del modelo trae `value`, `unit`, `label` (OBSERVADO, CALIBRADO, ESTIMADO, SUPUESTO), `source` y `date`.
El script no simula: solo agrega cotas analíticas simples en `checks` para revisar el modelo.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from datetime import date
from pathlib import Path

from app.catalog import load_catalog
from app.ingest import extract
from app.ingest.iac import scan_deployment  # JAJ-60: archivos de despliegue

RANK = {"OBSERVADO": 0, "CALIBRADO": 1, "ESTIMADO": 2, "SUPUESTO": 3}
HOURS_MONTH = 730
SECONDS_MONTH = 30 * 86400
TODAY = date.today().isoformat()


# ---------- números con procedencia ----------
def num(value, unit, label, source, *, default=False, **extra) -> dict:
    out = {"value": value, "unit": unit, "label": label, "source": source, "date": extra.pop("date", TODAY)}
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
        date=entry.get("date", TODAY),
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


# ---------- configuración que se lee del repo (OBSERVADO) ----------
SKIP = {".git", "node_modules", ".venv", "venv", "__pycache__"}
RUN_FILES = (
    "Dockerfile*",
    "*.Dockerfile",
    "docker-compose*.y*ml",
    "compose*.y*ml",
    "Procfile",
    "*.sh",
    "gunicorn*.py",
    "start*.py",
)


def _files(repo: Path, patterns) -> list[Path]:
    out = set()
    for pat in patterns:
        for p in repo.rglob(pat):
            if p.is_file() and not any(part in SKIP for part in p.relative_to(repo).parts):
                out.add(p)
    return sorted(out)


def read_workers(repo: Path) -> tuple[int, str] | None:
    """Workers del servidor: `--workers N` / `-w N` en Dockerfile, compose, Procfile o scripts; `workers = N` en gunicorn."""
    for path in _files(repo, RUN_FILES):
        for i, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            m = re.search(r"(?:--workers|\s-w)[\s=\"',]+(\d+)", line)
            if m and re.search(r"uvicorn|gunicorn|fastapi|hypercorn", line):
                return int(m.group(1)), f"{path.relative_to(repo)}:{i}"
            m = re.match(r"\s*workers\s*=\s*(\d+)", line)
            if m and path.suffix == ".py":
                return int(m.group(1)), f"{path.relative_to(repo)}:{i}"
    return None


def _config_default(proj: extract.Project, name: str) -> tuple[int, str] | None:
    """Valor por defecto de settings.X / config.X: `x: int = 10` o `X = config("X", default=20)`."""
    for mod in proj.modules.values():
        for node in ast.walk(mod.tree):
            target = val = None
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                target, val = node.target.id, node.value
            elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                target, val = node.targets[0].id, node.value
            if target is None or target.lower() != name.lower() or val is None:
                continue
            if isinstance(val, ast.Call):
                val = extract._kw(val, "default")
            if isinstance(val, ast.Constant) and isinstance(val.value, int) and not isinstance(val.value, bool):
                return val.value, f"{mod.rel}:{node.lineno}"
    return None


def _resolve_int(proj, mod, expr) -> tuple[int, str, bool] | None:
    """(valor, archivo:línea, viene_de_config). Constante en la llamada o default de la configuración."""
    if isinstance(expr, ast.Constant) and isinstance(expr.value, int):
        return expr.value, f"{mod.rel}:{expr.lineno}", False
    attr = expr.attr if isinstance(expr, ast.Attribute) else expr.id if isinstance(expr, ast.Name) else None
    hit = _config_default(proj, attr) if attr else None
    return (hit[0], hit[1], True) if hit else None


def default_pool(why: str) -> dict:
    """El pool por defecto de SQLAlchemy, como SUPUESTO por revisar, cuando el repo no dice el suyo."""
    cat = CATALOG["pools"]["sqlalchemy"]
    return {
        "library": "sqlalchemy",
        "defined_at": None,
        **{
            k: num(cat[k]["value"], cat[k]["unit"], "SUPUESTO", f"{why}. {cat[k]['source']}", default=True)
            for k in ("pool_size", "max_overflow", "pool_timeout_s")
        },
    }


def read_pool(proj: extract.Project) -> dict:
    """Busca create_engine / create_async_engine / asyncpg.create_pool y lee el tamaño del pool."""
    found = []
    for mod in proj.modules.values():
        dicts = {}
        for node in ast.walk(mod.tree):
            if (
                isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Dict)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
            ):
                dicts[node.targets[0].id] = node.value
        for node in ast.walk(mod.tree):
            if not isinstance(node, ast.Call):
                continue
            fn = extract._name(node.func).split(".")[-1]
            if fn not in ("create_engine", "create_async_engine", "create_pool"):
                continue
            kwargs = {k.arg: k.value for k in node.keywords if k.arg}
            for k in node.keywords:  # create_engine(url, **kwargs) con un dict literal en el mismo módulo
                if k.arg is None and isinstance(k.value, ast.Name) and k.value.id in dicts:
                    d = dicts[k.value.id]
                    kwargs.update(
                        {key.value: v for key, v in zip(d.keys, d.values, strict=True) if isinstance(key, ast.Constant)}
                    )
            kind = "asyncpg" if fn == "create_pool" else "sqlalchemy"
            if kind == "asyncpg" and "max_size" in kwargs:
                kwargs["pool_size"] = kwargs["max_size"]
            found.append((mod.name.endswith("env"), -len(kwargs), mod, node, kind, kwargs))
    if not found:
        # Sin create_engine visible (lo arma una librería, o la app no usa SQLAlchemy): se asume el pool
        # por defecto de SQLAlchemy, por revisar. Antes de JAJ-57 esto rompía checks() con un KeyError.
        return default_pool("No se encontró create_engine en el repo: se asume el default de SQLAlchemy")
    _, _, mod, node, kind, kwargs = sorted(found, key=lambda f: (f[0], f[1]))[0]  # se evitan los env.py de migraciones
    cat = CATALOG["pools"][kind]
    where = f"{mod.rel}:{node.lineno}"
    out = {"library": kind, "defined_at": where}
    if "poolclass" in kwargs and "NullPool" in extract._name(kwargs["poolclass"]):
        out["pool_size"] = num(0, "conexiones", "OBSERVADO", f"NullPool en {where}: una conexión nueva por request")
        out["max_overflow"] = num(None, "conexiones", "OBSERVADO", f"NullPool en {where}: sin tope en la app")
        return out
    for key, kw in (("pool_size", "pool_size"), ("max_overflow", "max_overflow"), ("pool_timeout_s", "pool_timeout")):
        hit = _resolve_int(proj, mod, kwargs[kw]) if kw in kwargs else None
        if hit:
            val, at, via_config = hit
            src = (
                f"default de la configuración en {at} (se puede cambiar por variable de entorno)"
                if via_config
                else f"{kw}={val} en {at}"
            )
            out[key] = num(val, cat[key]["unit"], "OBSERVADO", src)
        else:
            out[key] = from_catalog(
                cat[key], source=f"{cat[key]['source']}. El repo no lo configura ({where})", label="ESTIMADO"
            )
    return out


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
        # verificó un extractor, así que el número no puede ser más fuerte que ESTIMADO.
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
        # El motor ya simula el SET después de on_miss, incluso si el AST lo detectó aparte.
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
    # La CPU propia de FastAPI depende de si el endpoint es async (event loop) o def (threadpool, JAJ-46)
    base_cpu = from_catalog(CATALOG["api"]["cpu_ms" if ep.get("async") else "cpu_ms_sync"])
    if ep.get("origin") and ep["origin"].get("framework") != "fastapi":
        # El catálogo midió la CPU propia de FastAPI; en otro framework es un supuesto (JAJ-85).
        base_cpu = {
            **base_cpu,
            "label": "SUPUESTO",
            "source": f"{base_cpu['source']}. Medido en FastAPI; el repo usa {ep['origin']['framework']}",
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
        "CPU base de FastAPI + CPU pesada del endpoint",
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


# ---------- de 1 núcleo del laptop a la nube (JAJ-46) ----------
def core_factor(plan: dict, where: str) -> dict:
    """Cuántas veces más lento es 1 vCPU del plan que el núcleo donde se calibraron los tiempos."""
    proc = plan.get("processor", "local")
    f = CATALOG["cpu_core_factor"][proc]
    label = weakest(f["label"], plan.get("processor_label", f["label"]))
    return num(
        f["value"],
        "×",
        label,
        f"{where}: procesador {proc}. {f['source']}. {CATALOG['cpu_core_factor']['_doc']}",
        default=True,
        processor=proc,
    )


def cpu_credits(plan_name: str, vcpu: dict) -> dict | None:
    """Instancias con créditos (db.t4g): con carga sostenida rinden la base, no los vCPU nominales."""
    base = CATALOG["burstable_baseline_per_vcpu"].get(plan_name)
    if base is None:
        return None
    per_vcpu = from_catalog(base)
    sustained = derived(
        round(vcpu["value"] * per_vcpu["value"], 3),
        "vCPU",
        f"vCPU × base por vCPU: lo que rinde {plan_name} con carga sostenida. En modo unlimited "
        "rinde los vCPU nominales y cobra el exceso",
        vcpu,
        per_vcpu,
    )
    return {"baseline_per_vcpu": per_vcpu, "sustained_vcpu": sustained}


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
            "JAJ-11: perfil medio, sin dato del usuario",
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
        rps_session = num(prof["requests_per_session"], "requests/sesión", "SUPUESTO", f"Perfil {prof_name} de JAJ-11")
        avg = mau["value"] * prof["sessions_per_month"] * prof["requests_per_session"] / SECONDS_MONTH
        peak = derived(
            round(avg * k_hour["value"], 2),
            "req/s",
            "usuarios/mes × sesiones/mes × requests/sesión / segundos del mes × K_hora (JAJ-11)",
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


def deployment_model(ans: dict, workers: dict, pool: dict, iac: dict) -> dict:
    d = ans.get("deployment", {})
    seen = iac["observed"]
    dbp = d.get("db", {"provider": "local", "plan": "docker"})
    plans = CATALOG["db_plans"]
    plan = plans[dbp["provider"]][dbp["plan"]]
    src = f"{plans['_sources'][dbp['provider']]}. Plan {dbp['provider']} {dbp['plan']} declarado por el usuario"
    if dbp["provider"] == "supabase":
        usd = plans["supabase_base_usd_month"] + max(
            0, plan["compute_usd_month"] - plans["supabase_compute_credit_usd_month"]
        )
    else:
        usd = plan["usd_hour"] * HOURS_MONTH
    db = {
        "provider": dbp["provider"],
        "plan": dbp["plan"],
        "vcpu": num(plan["vcpu"], "vCPU", plan["vcpu_label"], src),
        "max_connections": num(plan["max_connections"], "conexiones", "ESTIMADO", src),
        "usd_month": num(
            round(usd, 2),
            "US$/mes",
            "ESTIMADO",
            f"{src}. Supabase: 25 + max(0, compute − 10); RDS: US$/hora × 730 (JAJ-11)",
        ),
        "pool_per_worker": pool,
        "cpu_core_factor": core_factor(plan, f"Plan {dbp['provider']} {dbp['plan']}"),
    }
    credits = cpu_credits(dbp["plan"], db["vcpu"])
    if credits:
        db["cpu_credits"] = credits
    if "pooler_connections" in plan:
        db["pooler_connections"] = num(plan["pooler_connections"], "conexiones", "ESTIMADO", src)
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
    provider = a.get("provider", "local")
    price = CATALOG["app_plans"][provider]
    replicas, vcpu, mem = api_vals["replicas"], api_vals["vcpu"], api_vals["memory_gb"]
    api_usd = (
        replicas["value"] * (vcpu["value"] * price["usd_vcpu_hour"] + mem["value"] * price["usd_gb_hour"]) * HOURS_MONTH
    )
    api = {
        "provider": provider,
        "replicas": replicas,
        "vcpu": vcpu,
        "memory_gb": mem,
        "workers": workers,
        "threads_per_worker": from_catalog(CATALOG["api"]["threads_per_worker"]),
        "latency_ms": from_catalog(CATALOG["api"]["latency_ms"]),
        "usd_month": num(round(api_usd, 2), "US$/mes", "ESTIMADO", CATALOG["app_plans"]["_source"]),
        "cpu_core_factor": core_factor(price, f"API en {provider}"),
    }
    # Lo que el agente tiene que preguntar (JAJ-59): lo que no dicen ni el repo ni las respuestas
    answered = {f"api.{k}" for k in a} | ({"db.plan"} if "db" in d else set())
    return {
        "api": api,
        "db": db,
        "services": iac["services"],
        "iac": {
            "files": iac["files"],
            "deploy_targets": iac["deploy_targets"],
            "warnings": iac["warnings"],
            "missing": [m for m in iac["missing"] if m["field"] not in answered],
        },
    }


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
            "nube (los tiempos de JAJ-8 son de 1 núcleo del laptop × cpu_core_factor)",
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
        bottleneck = min(valid, key=lambda k: valid[k]["value"])
        sessions_h = rps * 3600 / t["requests_per_session"]["value"]
        at_stake = derived(
            round(sessions_h * biz["conversion"]["value"] * biz["ticket_usd"]["value"], 0),
            "US$/hora",
            "sesiones/hora × conversión × ticket: ventas en juego por hora si el sistema se cae (JAJ-11)",
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
        "_doc": "Cotas analíticas simples para revisar el modelo. No reemplazan la simulación (JAJ-9).",
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
    """El extractor no encontró endpoints que modelar en el repo."""


NO_ENDPOINTS = (
    "No encontramos endpoints en ese repo y esa rama. El extractor automático lee apps FastAPI; para otro "
    "framework (Express, Django, Spring, Go...), abre el repo en tu CLI de IA conectada a Branchpoint por MCP "
    "y pídele que lo analice con submit_architecture."
)


def build(repo: Path, answers: dict) -> dict:
    """Modelo de un repo FastAPI: el extractor AST arma el grafo y ``build_from_graph`` el modelo."""
    graph = extract.run(repo)
    if not graph["endpoints"]:
        raise NoEndpoints(NO_ENDPOINTS)
    proj = extract.Project(repo)
    proj.load()
    iac = scan_deployment(repo).to_dict()
    w = read_workers(repo)
    if w:
        workers = num(w[0], "procesos", "OBSERVADO", f"{w[0]} workers en {w[1]}")
    elif "api.workers" in iac["observed"]:
        workers = iac["observed"]["api.workers"]
    else:
        workers = from_catalog(CATALOG["api"]["workers_default"])
    return build_from_graph(graph, repo.name, answers, iac=iac, workers=workers, pool=read_pool(proj))


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

    El grafo es el de ``extract.run`` (endpoints → efectos con forma y ``archivo:línea``). Lo produce el
    extractor AST de FastAPI o, para otros frameworks, la IA del usuario (``app/ingest/ai_graph.py``).
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
            "extracted_at": TODAY,
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
    ap.add_argument("repo", type=Path)
    ap.add_argument("--answers", type=Path, help="respuestas del usuario; sin ellas, supuestos del catálogo")
    ap.add_argument("-o", "--out", type=Path)
    args = ap.parse_args()
    answers = json.loads(args.answers.read_text(encoding="utf-8")) if args.answers else {}
    model = build(args.repo.resolve(), answers)
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
