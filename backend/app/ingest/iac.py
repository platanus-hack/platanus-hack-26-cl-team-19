"""Lee los archivos de despliegue de un repo para completar el ``deployment`` del modelo (JAJ-60).

Antes de preguntarle la infraestructura al usuario, se busca en el repo. Es determinista: no hay LLM
ni red, y no depende del framework del backend (lee archivos de despliegue, no el código). Lee:

* Docker Compose (``compose*.yml``, ``docker-compose*.yml``): servicios y su rol (API, DB, caché, cola,
  worker, proxy), réplicas (``deploy.replicas``, ``scale``) y límites (``deploy.resources.limits``).
* ``Dockerfile``, ``Procfile`` y el ``command`` de cada servicio: qué servidor corre (Node, PM2,
  uvicorn, gunicorn, Puma, Java, Go...) y cuántos procesos levanta.
* Kubernetes (``Deployment``, ``StatefulSet``, ``HorizontalPodAutoscaler``): réplicas y ``resources``.
* ``fly.toml``, ``render.yaml`` y Terraform de AWS (RDS, ECS, ElastiCache, SQS).
* Workflows de GitHub Actions: a dónde se despliega (solo como pista).

Cada número sale con procedencia ``OBSERVADO`` y ``at`` (``archivo:línea``), en el formato de JAJ-45.
``missing`` dice qué no se encontró, con la pregunta para el agente (JAJ-59): así pregunta solo eso.
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

try:  # PyYAML es dependencia del backend; sin ella se leen igual Dockerfile, Terraform y fly.toml
    import yaml
except ImportError:  # pragma: no cover - solo pasa fuera del backend (ej. el spike sin instalar)
    yaml = None

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".terraform"}
MAX_FILE_BYTES = 512 * 1024

COMPOSE_RE = re.compile(r"^(docker-)?compose([.-][\w.-]+)?\.ya?ml$")
DOCKERFILE_RE = re.compile(r"^(Dockerfile([.-][\w.-]+)?|[\w.-]+\.Dockerfile)$")

# rol de un servicio según su imagen (o el nombre del servicio si se construye desde el repo)
ROLE_BY_IMAGE = [
    ("db", re.compile(r"(^|/)(postgres|postgis|timescale|mysql|mariadb|mongo|cockroach)")),
    ("cache", re.compile(r"(^|/)(redis|valkey|keydb|memcached|dragonfly)")),
    ("queue", re.compile(r"(^|/)(rabbitmq|nats|kafka|bitnami/kafka|confluentinc/cp-kafka|localstack)")),
    ("proxy", re.compile(r"(^|/)(traefik|nginx|caddy|haproxy|envoy)")),
]
WORKER_CMD = re.compile(
    r"\b(celery\b.*\bworker|rq\s+worker|arq\b|dramatiq|huey_consumer|taskiq\s+worker|sidekiq|resque|good_job"
    r"|solid_queue|artisan\s+queue:work|bullmq|worker\.(js|ts|mjs))"
)
# Servidores HTTP de cualquier runtime: un servicio que corre uno de estos es la API.
API_CMD = re.compile(
    r"\b(uvicorn|gunicorn|hypercorn|granian|daphne|fastapi\s+(run|dev)|manage\.py\s+runserver|flask\s+run"
    r"|node|nodemon|ts-node|tsx|bun|deno|pm2(-runtime)?|(npm|yarn|pnpm)\s+(run\s+)?(start|serve|prod)"
    r"|(nest|next|nuxt)\s+start|java\b.*-jar|go\s+run|rails\s+s(erver)?|puma|unicorn|dotnet"
    r"|php-fpm|artisan\s+serve|frankenphp)\b"
)
PM2_INSTANCES = re.compile(r"\bpm2(?:-runtime)?\b.*?(?:\s-i|--instances)[\s=]+(\d+)")
WORKERS_FLAG = re.compile(r"(?:--workers|--concurrency|(?<![\w-])-w|(?<![\w-])-c)[\s=\"',]+(\d+)")
CELERY_QUEUES_FLAG = re.compile(r"(?:^|\s)(?:--queues|-Q)[\s=]+['\"]?([^\s'\"]+)")


def num(value: Any, unit: str, source: str, at: str) -> dict[str, Any]:
    return {
        "value": value,
        "unit": unit,
        "label": "OBSERVADO",
        "source": source,
        "date": date.today().isoformat(),
        "at": at,
    }


@dataclass
class Service:
    name: str
    role: str  # api, db, cache, queue, worker, proxy, other
    at: str
    image: str | None = None
    engine: str | None = None  # postgres, redis, ... (de la imagen)
    version: str | None = None
    replicas: dict | None = None
    vcpu: dict | None = None
    memory_gb: dict | None = None
    workers: dict | None = None
    plan: dict | None = None  # db.t4g.micro, starter, ... cuando el archivo lo dice
    source_file: str = ""
    queue: str | None = None  # suscripción exclusiva del worker a una cola

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v not in (None, "")}


@dataclass
class Findings:
    files: list[dict[str, str]] = field(default_factory=list)
    services: list[Service] = field(default_factory=list)
    deploy_targets: list[dict[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def by_role(self, role: str) -> list[Service]:
        return [s for s in self.services if s.role == role]

    def to_dict(self) -> dict[str, Any]:
        return {
            "files": self.files,
            "services": [s.to_dict() for s in self.services],
            "observed": observed(self),
            "missing": missing(self),
            "deploy_targets": self.deploy_targets,
            "warnings": self.warnings,
        }


# ---------- búsqueda de archivos ----------


def _walk(repo: Path):
    for p in sorted(repo.rglob("*")):
        rel = p.relative_to(repo)
        if any(part in SKIP_DIRS for part in rel.parts[:-1]) or not p.is_file():
            continue
        if p.is_symlink() or p.stat().st_size > MAX_FILE_BYTES:
            continue
        yield p, rel.as_posix()


def _text(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


# ---------- YAML con número de línea ----------

if yaml is not None:

    class _LineLoader(yaml.SafeLoader):
        """Como SafeLoader, pero cada mapping guarda la línea de cada clave en ``__lines__``."""

        def construct_mapping(self, node, deep=False):
            mapping = super().construct_mapping(node, deep=True)
            mapping["__lines__"] = {
                k.value: k.start_mark.line + 1 for k, _ in node.value if isinstance(k, yaml.ScalarNode)
            }
            mapping["__line__"] = node.start_mark.line + 1
            return mapping


def _yaml_docs(text: str, rel: str, findings: Findings) -> list[Any]:
    if yaml is None:
        findings.warnings.append(f"{rel}: no se leyó porque falta PyYAML (pip install pyyaml)")
        return []
    try:
        return [d for d in yaml.load_all(text, Loader=_LineLoader) if d is not None]  # noqa: S506 (SafeLoader)
    except yaml.YAMLError as e:
        findings.warnings.append(f"{rel}: YAML inválido ({str(e).splitlines()[0]})")
        return []


def _line(mapping: dict, key: str) -> int:
    return mapping.get("__lines__", {}).get(key, mapping.get("__line__", 1))


# ---------- workers en comandos ----------


def _workers_in(cmd: str, warnings: list[str] | None = None) -> int | None:
    """Procesos del servidor: ``--workers N`` (uvicorn, gunicorn, Puma...) o ``pm2 -i N``. Sin la opción,
    los servidores de ``API_CMD`` levantan un solo proceso.

    ``--workers 0`` no levanta procesos que atiendan requests: se descarta (``None``, queda el valor por
    defecto, por revisar) y, si se pasa ``warnings``, se avisa ahí (JAJ-108)."""
    if not API_CMD.search(cmd) and not WORKER_CMD.search(cmd):
        return None
    m = PM2_INSTANCES.search(cmd) or WORKERS_FLAG.search(cmd)
    if m:
        n = int(m.group(1))
        if n < 1:
            if warnings is not None:
                warnings.append(
                    f"«{cmd}» pide {n} procesos: se ignora, porque con 0 la API no atiende requests. "
                    "Queda el valor por defecto, por revisar."
                )
            return None
        return n
    return 1 if not WORKER_CMD.search(cmd) else None


def _dedicated_celery_queue(cmd: str) -> str | None:
    if not re.search(r"\bcelery\b.*\bworker\b", cmd):
        return None
    queues = CELERY_QUEUES_FLAG.findall(cmd)
    if len(queues) == 1 and re.fullmatch(r"[\w.-]+", queues[0]):
        return queues[0]
    return None


def _workers_source(w: int, cmd: str, where: str) -> str:
    if PM2_INSTANCES.search(cmd) or WORKERS_FLAG.search(cmd):
        return f"{w} workers en {where}"
    return f"{where} no pasa --workers: el servidor levanta 1 proceso por defecto"


def _cmd_text(value: Any) -> str:
    if isinstance(value, list):
        return " ".join(str(v) for v in value)
    return str(value or "")


def _exec_form(arg: str) -> str:
    """``["fastapi", "run", "--workers", "4"]`` (forma exec) -> ``fastapi run --workers 4``."""
    arg = arg.strip()
    if arg.startswith("["):
        try:
            return " ".join(str(x) for x in json.loads(arg))
        except json.JSONDecodeError:
            pass
    return arg


def dockerfile_cmd(path: Path, rel: str) -> tuple[str, str] | None:
    """El último CMD/ENTRYPOINT del Dockerfile (el de la etapa final), con su línea y sus continuaciones."""
    lines = _text(path).splitlines()
    last = None
    for i, line in enumerate(lines):
        m = re.match(r"\s*(CMD|ENTRYPOINT)\s+(.*)", line, re.IGNORECASE)
        if m:
            arg, j = m.group(2), i
            while arg.rstrip().endswith("\\") and j + 1 < len(lines):  # CMD partido con \
                j += 1
                arg = arg.rstrip()[:-1] + " " + lines[j].strip()
            last = (_exec_form(arg), f"{rel}:{i + 1}")
    return last


# ---------- Docker Compose ----------


def _role(name: str, image: str | None, command: str, built: bool) -> str:
    if WORKER_CMD.search(command):
        return "worker"
    if image:
        for role, rx in ROLE_BY_IMAGE:
            if rx.search(image.lower()):
                return role
    if API_CMD.search(command):
        return "api"
    return "other"  # se construye desde el repo, pero no corre un servidor reconocible (ej. tests e2e)


def _engine(image: str | None) -> tuple[str | None, str | None]:
    if not image:
        return None, None
    base = image.split("/")[-1]
    name, _, tag = base.partition(":")
    return name, (tag or None)


def _cpus(value: Any) -> float | None:
    """'0.5', 2, '500m' (Kubernetes) -> vCPU."""
    s = str(value).strip().strip("'\"")
    try:
        return float(s[:-1]) / 1000 if s.endswith("m") else float(s)
    except ValueError:
        return None


def _memory_gb(value: Any) -> float | None:
    """'512M', '2g', '1Gi', '2048Mi' -> GB."""
    m = re.fullmatch(r"\s*([\d.]+)\s*([kmgt]?)i?b?\s*", str(value).lower())
    if not m:
        return None
    n, unit = float(m.group(1)), m.group(2)
    return round(n * {"": 1e-9, "k": 1e-6, "m": 1e-3, "g": 1, "t": 1e3}[unit], 3)


def read_compose(path: Path, rel: str, repo: Path, findings: Findings) -> None:
    for doc in _yaml_docs(_text(path), rel, findings):
        services = doc.get("services") if isinstance(doc, dict) else None
        if not isinstance(services, dict):
            continue
        for name, svc in services.items():
            if name.startswith("__") or not isinstance(svc, dict):
                continue
            at = f"{rel}:{_line(services, name)}"
            existing = next(
                (s for s in findings.services if s.name == name and s.source_file.startswith("compose")), None
            )
            image = svc.get("image")
            built = "build" in svc
            command = _cmd_text(svc.get("command"))
            cmd_at = f"{rel}:{_line(svc, 'command')}"
            cmd_where = f"el command de {name}"
            if not command and built:  # sin command: el CMD del Dockerfile que construye
                build = svc["build"] if isinstance(svc["build"], dict) else {"context": svc["build"]}
                ctx = path.parent / str(build.get("context", "."))
                df = ctx / str(build.get("dockerfile", "Dockerfile"))
                if df.is_file():
                    hit = dockerfile_cmd(df, df.resolve().relative_to(repo.resolve()).as_posix())
                    if hit:
                        command, cmd_at = hit
                        cmd_where = f"el CMD del Dockerfile de {name}"
            if existing is None:
                role = _role(name, image, command, built)
                engine, version = _engine(image) if role in ("db", "cache", "queue", "proxy") else (None, None)
                existing = Service(name, role, at, image, engine, version, source_file=f"compose:{rel}")
                findings.services.append(existing)
            elif image and not existing.image:  # un override completa al archivo base
                existing.image = image
            w = _workers_in(command, findings.warnings)
            if w:
                existing.workers = num(w, "procesos", _workers_source(w, command, cmd_where), cmd_at)
            if command:
                existing.queue = _dedicated_celery_queue(command)
            deploy = svc.get("deploy") if isinstance(svc.get("deploy"), dict) else {}
            if "replicas" in deploy:
                existing.replicas = num(
                    int(deploy["replicas"]),
                    "réplicas",
                    f"deploy.replicas de {name}",
                    f"{rel}:{_line(deploy, 'replicas')}",
                )
            elif "scale" in svc:
                existing.replicas = num(
                    int(svc["scale"]), "réplicas", f"scale de {name}", f"{rel}:{_line(svc, 'scale')}"
                )
            limits = ((deploy.get("resources") or {}).get("limits")) or {}
            if isinstance(limits, dict):
                if "cpus" in limits and (c := _cpus(limits["cpus"])) is not None:
                    existing.vcpu = num(c, "vCPU", f"límite de CPU de {name}", f"{rel}:{_line(limits, 'cpus')}")
                if "memory" in limits and (g := _memory_gb(limits["memory"])) is not None:
                    existing.memory_gb = num(
                        g, "GB", f"límite de memoria de {name}", f"{rel}:{_line(limits, 'memory')}"
                    )


# ---------- Kubernetes ----------


def read_kubernetes(path: Path, rel: str, findings: Findings) -> None:
    for doc in _yaml_docs(_text(path), rel, findings):
        if not isinstance(doc, dict) or "kind" not in doc:
            continue
        kind, meta = doc["kind"], doc.get("metadata") or {}
        name = meta.get("name", "?")
        at = f"{rel}:{doc.get('__line__', 1)}"
        spec = doc.get("spec") or {}
        if kind in ("Deployment", "StatefulSet"):
            containers = (((spec.get("template") or {}).get("spec") or {}).get("containers")) or []
            c0 = containers[0] if containers and isinstance(containers[0], dict) else {}
            image = c0.get("image")
            command = _cmd_text((c0.get("command") or []) + (c0.get("args") or []))
            role = _role(name, image, command, built=False)
            engine, version = _engine(image) if role in ("db", "cache", "queue", "proxy") else (None, None)
            svc = Service(name, role, at, image, engine, version, source_file=f"k8s:{rel}")
            if "replicas" in spec:
                svc.replicas = num(
                    int(spec["replicas"]),
                    "réplicas",
                    f"spec.replicas del {kind} {name}",
                    f"{rel}:{_line(spec, 'replicas')}",
                )
            res = c0.get("resources") or {}
            for part in ("limits", "requests"):  # el límite manda; si no hay, el request
                r = res.get(part) or {}
                if svc.vcpu is None and "cpu" in r and (c := _cpus(r["cpu"])) is not None:
                    svc.vcpu = num(c, "vCPU", f"resources.{part}.cpu de {name}", f"{rel}:{_line(r, 'cpu')}")
                if svc.memory_gb is None and "memory" in r and (g := _memory_gb(r["memory"])) is not None:
                    svc.memory_gb = num(g, "GB", f"resources.{part}.memory de {name}", f"{rel}:{_line(r, 'memory')}")
            w = _workers_in(command, findings.warnings)
            if w:
                svc.workers = num(w, "procesos", _workers_source(w, command, f"el contenedor de {name}"), at)
            svc.queue = _dedicated_celery_queue(command)
            findings.services.append(svc)
        elif kind == "HorizontalPodAutoscaler":
            target = (spec.get("scaleTargetRef") or {}).get("name")
            svc = next((s for s in findings.services if s.name == target), None)
            if svc and "maxReplicas" in spec:
                # para un pico importa cuántas réplicas puede llegar a tener
                svc.replicas = num(
                    int(spec["maxReplicas"]),
                    "réplicas",
                    f"maxReplicas del HPA {name} (mínimo {spec.get('minReplicas', 1)})",
                    f"{rel}:{_line(spec, 'maxReplicas')}",
                )


# ---------- fly.toml y render.yaml ----------


def read_fly(path: Path, rel: str, findings: Findings) -> None:
    text = _text(path)
    try:
        cfg = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        findings.warnings.append(f"{rel}: TOML inválido ({e})")
        return
    lines = text.splitlines()

    def line_of(pattern: str) -> int:
        return next((i for i, ln in enumerate(lines, 1) if re.match(pattern, ln.strip())), 1)

    svc = Service(cfg.get("app", "app"), "api", f"{rel}:1", source_file=f"fly:{rel}")
    vms = cfg.get("vm") or []
    vm = vms[0] if isinstance(vms, list) and vms else vms if isinstance(vms, dict) else {}
    if "cpus" in vm:
        svc.vcpu = num(float(vm["cpus"]), "vCPU", "[[vm]] cpus de fly.toml", f"{rel}:{line_of(r'cpus\s*=')}")
    mem = vm.get("memory") or vm.get("memory_mb")
    if mem is not None:
        g = _memory_gb(f"{mem}m" if isinstance(mem, int) else mem)
        if g is not None:
            svc.memory_gb = num(g, "GB", "[[vm]] memory de fly.toml", f"{rel}:{line_of(r'memory(_mb)?\s*=')}")
    http = cfg.get("http_service") or {}
    if "min_machines_running" in http:
        svc.replicas = num(
            int(http["min_machines_running"]),
            "réplicas",
            "http_service.min_machines_running de fly.toml",
            f"{rel}:{line_of(r'min_machines_running\s*=')}",
        )
    findings.services.append(svc)
    findings.deploy_targets.append({"target": "fly", "at": f"{rel}:1"})


RENDER_TYPES = {"web": "api", "worker": "worker", "pserv": "api", "redis": "cache", "keyvalue": "cache"}


def read_render(path: Path, rel: str, findings: Findings) -> None:
    for doc in _yaml_docs(_text(path), rel, findings):
        if not isinstance(doc, dict):
            continue
        for svc in doc.get("services") or []:
            if not isinstance(svc, dict):
                continue
            s = Service(
                svc.get("name", "?"),
                RENDER_TYPES.get(svc.get("type"), "other"),
                f"{rel}:{svc['__line__']}",
                source_file=f"render:{rel}",
            )
            if "plan" in svc:
                s.plan = num(svc["plan"], "plan", f"plan de Render de {s.name}", f"{rel}:{_line(svc, 'plan')}")
            scaling = svc.get("scaling") or {}
            if "maxInstances" in scaling:
                s.replicas = num(
                    int(scaling["maxInstances"]),
                    "réplicas",
                    f"scaling.maxInstances de {s.name}",
                    f"{rel}:{_line(scaling, 'maxInstances')}",
                )
            elif "numInstances" in svc:
                s.replicas = num(
                    int(svc["numInstances"]),
                    "réplicas",
                    f"numInstances de {s.name}",
                    f"{rel}:{_line(svc, 'numInstances')}",
                )
            w = _workers_in(_cmd_text(svc.get("startCommand")), findings.warnings)
            if w:
                cmd = _cmd_text(svc.get("startCommand"))
                s.workers = num(
                    w,
                    "procesos",
                    _workers_source(w, cmd, f"startCommand de {s.name}"),
                    f"{rel}:{_line(svc, 'startCommand')}",
                )
            findings.services.append(s)
        for db in doc.get("databases") or []:
            if isinstance(db, dict):
                s = Service(
                    db.get("name", "db"),
                    "db",
                    f"{rel}:{db['__line__']}",
                    engine="postgres",
                    source_file=f"render:{rel}",
                )
                if "plan" in db:
                    s.plan = num(
                        db["plan"], "plan", f"plan de Postgres de Render de {s.name}", f"{rel}:{_line(db, 'plan')}"
                    )
                findings.services.append(s)
        findings.deploy_targets.append({"target": "render", "at": f"{rel}:1"})


# ---------- Terraform (AWS) ----------

TF_RESOURCE = re.compile(r'^\s*resource\s+"(?P<type>[\w-]+)"\s+"(?P<name>[\w-]+)"\s*\{')
TF_ATTR = re.compile(r'^\s*(?P<key>[\w-]+)\s*=\s*"?(?P<val>[^"#\n]*?)"?\s*(#.*)?$')
TF_ROLES = {
    "aws_db_instance": "db",
    "aws_rds_cluster": "db",
    "aws_rds_cluster_instance": "db",
    "aws_elasticache_cluster": "cache",
    "aws_elasticache_replication_group": "cache",
    "aws_sqs_queue": "queue",
    "aws_mq_broker": "queue",
    "aws_ecs_service": "api",
    "aws_ecs_task_definition": "api",
    "aws_apprunner_service": "api",
}


def _tf_blocks(text: str):
    """(tipo, nombre, línea, {atributo: (valor, línea)}) de cada resource, solo atributos de primer nivel."""
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        m = TF_RESOURCE.match(lines[i])
        if not m:
            i += 1
            continue
        start, depth, attrs = i + 1, lines[i].count("{") - lines[i].count("}"), {}
        i += 1
        while i < len(lines) and depth > 0:
            ln = lines[i]
            if depth == 1 and (a := TF_ATTR.match(ln)):
                attrs[a.group("key")] = (a.group("val").strip(), i + 1)
            depth += ln.count("{") - ln.count("}")
            i += 1
        yield m.group("type"), m.group("name"), start, attrs


def read_terraform(path: Path, rel: str, findings: Findings) -> None:
    for rtype, name, line, attrs in _tf_blocks(_text(path)):
        role = TF_ROLES.get(rtype)
        if role is None:
            continue
        at = f"{rel}:{line}"
        if rtype == "aws_ecs_task_definition":  # completa el aws_ecs_service, o queda como la API
            svc = next((s for s in findings.services if s.source_file == f"tf:{rel}" and s.role == "api"), None)
            if svc is None:
                svc = Service(name, "api", at, source_file=f"tf:{rel}")
                findings.services.append(svc)
            if "cpu" in attrs and attrs["cpu"][0].isdigit():  # unidades de CPU de ECS: 1024 = 1 vCPU
                v, ln = attrs["cpu"]
                svc.vcpu = num(int(v) / 1024, "vCPU", f"cpu = {v} (unidades de ECS) en {name}", f"{rel}:{ln}")
            if "memory" in attrs and attrs["memory"][0].isdigit():
                v, ln = attrs["memory"]
                svc.memory_gb = num(int(v) / 1024, "GB", f"memory = {v} MiB en {name}", f"{rel}:{ln}")
            continue
        svc = Service(name, role, at, engine=attrs.get("engine", (None,))[0], source_file=f"tf:{rel}")
        for key in ("instance_class", "node_type"):
            if key in attrs:
                v, ln = attrs[key]
                svc.plan = num(v, "plan", f"{key} de {rtype}.{name}", f"{rel}:{ln}")
        if "desired_count" in attrs and attrs["desired_count"][0].isdigit():
            v, ln = attrs["desired_count"]
            svc.replicas = num(int(v), "réplicas", f"desired_count de {name}", f"{rel}:{ln}")
        if "engine_version" in attrs:
            svc.version = attrs["engine_version"][0]
        findings.services.append(svc)
    if any(s.source_file == f"tf:{rel}" for s in findings.services):
        findings.deploy_targets.append({"target": "aws (terraform)", "at": f"{rel}:1"})


# ---------- Procfile y workflows ----------


def read_procfile(path: Path, rel: str, findings: Findings) -> None:
    for i, line in enumerate(_text(path).splitlines(), 1):
        kind, _, cmd = line.partition(":")
        if not cmd:
            continue
        role = (
            "worker"
            if WORKER_CMD.search(cmd) or kind.strip() == "worker"
            else "api"
            if API_CMD.search(cmd)
            else "other"
        )
        s = Service(kind.strip(), role, f"{rel}:{i}", source_file=f"procfile:{rel}")
        w = _workers_in(cmd, findings.warnings)
        if w:
            s.workers = num(w, "procesos", _workers_source(w, cmd, f"el Procfile ({kind.strip()})"), f"{rel}:{i}")
        findings.services.append(s)


DEPLOY_HINTS = [
    ("fly", re.compile(r"flyctl\s+deploy|superfly/flyctl-actions")),
    ("render", re.compile(r"render\.com/deploy|api\.render\.com")),
    ("fastapi cloud", re.compile(r"\bfastapi\s+deploy\b")),
    ("aws ecs", re.compile(r"amazon-ecs-deploy-task-definition|aws\s+ecs\s+update-service")),
    ("heroku", re.compile(r"heroku\s+(container:release|deploy)|akhileshns/heroku-deploy")),
    ("railway", re.compile(r"railway\s+up")),
    ("kubernetes", re.compile(r"kubectl\s+apply|helm\s+upgrade")),
    ("docker registry", re.compile(r"docker\s+push|docker/build-push-action")),
]


def read_workflow(path: Path, rel: str, findings: Findings) -> None:
    for i, line in enumerate(_text(path).splitlines(), 1):
        for target, rx in DEPLOY_HINTS:
            if rx.search(line):
                findings.deploy_targets.append({"target": target, "at": f"{rel}:{i}"})
                return


# ---------- entrada ----------


def scan_deployment(repo: Path) -> Findings:
    """Busca y lee los archivos de despliegue del repo. Un repo sin ninguno da ``Findings`` vacío."""
    repo = Path(repo)
    findings = Findings()
    compose, k8s, dockerfiles = [], [], []
    for path, rel in _walk(repo):
        name = path.name
        if COMPOSE_RE.match(name):
            compose.append((path, rel))
        elif DOCKERFILE_RE.match(name):
            dockerfiles.append((path, rel))
        elif name == "fly.toml":
            findings.files.append({"path": rel, "kind": "fly"})
            read_fly(path, rel, findings)
        elif name in ("render.yaml", "render.yml"):
            findings.files.append({"path": rel, "kind": "render"})
            read_render(path, rel, findings)
        elif name.endswith(".tf"):
            findings.files.append({"path": rel, "kind": "terraform"})
            read_terraform(path, rel, findings)
        elif name == "Procfile":
            findings.files.append({"path": rel, "kind": "procfile"})
            read_procfile(path, rel, findings)
        elif rel.startswith(".github/workflows/") and name.endswith((".yml", ".yaml")):
            read_workflow(path, rel, findings)
        elif name.endswith((".yml", ".yaml")) and re.search(
            r"^\s*kind:\s*(Deployment|StatefulSet)\b", _text(path), re.M
        ):
            k8s.append((path, rel))
    # El compose base antes que los override: así el override completa y no duplica servicios.
    for path, rel in sorted(compose, key=lambda pr: (len(pr[0].name), pr[1])):
        findings.files.append({"path": rel, "kind": "compose"})
        read_compose(path, rel, repo, findings)
    for path, rel in k8s:
        findings.files.append({"path": rel, "kind": "kubernetes"})
        read_kubernetes(path, rel, findings)
    for path, rel in dockerfiles:
        findings.files.append({"path": rel, "kind": "dockerfile"})
        # Sin compose ni otro orquestador, el Dockerfile de la raíz es la API
        if not findings.by_role("api"):
            hit = dockerfile_cmd(path, rel)
            if hit and API_CMD.search(hit[0]):
                svc = Service("app", "api", hit[1], source_file=f"dockerfile:{rel}")
                w = _workers_in(hit[0], findings.warnings)
                if w:
                    svc.workers = num(w, "procesos", _workers_source(w, hit[0], "el CMD del Dockerfile"), hit[1])
                findings.services.append(svc)
    return findings


# ---------- qué se encontró y qué falta (para el modelo y el agente) ----------

QUESTIONS = {
    "api.replicas": "¿Cuántas réplicas de la API corren en producción (o cuántas como máximo con autoescalado)?",
    "api.vcpu": "¿Cuántos vCPU tiene cada réplica de la API?",
    "api.memory_gb": "¿Cuánta memoria tiene cada réplica de la API?",
    "api.workers": "¿Cuántos procesos de la API corre cada réplica (workers, cluster, PM2)?",
    "api.provider": "¿Dónde corre la API (Fargate, Fly, Render, un servidor propio...)?",
    "db.plan": "¿Qué plan o tamaño de base de datos usan (por ejemplo Supabase Micro o RDS db.t4g.medium)?",
}


def _first(services: list[Service], attr: str) -> dict | None:
    return next((getattr(s, attr) for s in services if getattr(s, attr) is not None), None)


def observed(f: Findings) -> dict[str, Any]:
    """Los números del ``deployment`` que el repo sí dice. Solo lo encontrado, nunca un valor por defecto."""
    out: dict[str, Any] = {}
    api, db = f.by_role("api"), f.by_role("db")
    for attr in ("replicas", "vcpu", "memory_gb", "workers"):
        if (v := _first(api, attr)) is not None:
            out[f"api.{attr}"] = v
    if (v := _first(db, "plan")) is not None:
        out["db.plan"] = v
    targets = {t["target"] for t in f.deploy_targets} - {"docker registry"}
    if len(targets) == 1:
        t = next(iter(targets))
        at = next(x["at"] for x in f.deploy_targets if x["target"] == t)
        out["api.provider"] = num(t, "proveedor", "destino del despliegue en el repo", at)
    return out


def missing(f: Findings) -> list[dict[str, str]]:
    """Lo que el agente tiene que preguntar: cada campo que el repo no dice, con su pregunta."""
    found = observed(f)
    return [{"field": k, "question": q} for k, q in QUESTIONS.items() if k not in found]
