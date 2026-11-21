"""``ProjectStore`` sobre Postgres (JAJ-56): proyectos, versiones y escenarios en las tablas de
``supabase/migrations/``. El mapeo de cada método a SQL está en ``app/db/README.md``.

El backend se conecta con ``DATABASE_URL`` como el rol ``postgres``, que no pasa por RLS, así que el
aislamiento entre usuarios lo hace este store (JAJ-78): ``create`` guarda el ``owner_id`` y ``get`` y
``list`` filtran por él. Sin login, ``owner`` es ``None`` y se ven los proyectos sin dueño.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from app.api.store import (
    GitHubInstallation,
    Origin,
    Project,
    ProjectGoals,
    ProjectScenario,
    RepoSource,
    Version,
    scenarios_from_model,
)

_SUMMARY = "number, origin::text as origin, parent_number, note, created_at"
_PROJECT = "id, name, sample_id, created_at, owner_id"
# el proyecto con su repo (JAJ-92): repo_connections tiene el nombre, projects la rama analizada.
# left join: los proyectos de un ejemplo no tienen repo. La conexión es del mismo dueño (la crea la
# ingesta con el owner del proyecto), así que el filtro por p.owner_id basta para aislar.
_PROJECT_WITH_REPO = (
    "p.id, p.name, p.sample_id, p.created_at, p.owner_id, rc.repo_full_name, p.branch"
    " from projects p left join repo_connections rc on rc.id = p.repo_connection_id"
)


def _iso(ts: datetime) -> str:
    return ts.astimezone(UTC).isoformat(timespec="seconds")


def _uuid(project_id: str) -> uuid.UUID | None:
    """Los ids son uuid. Un id que no lo es no existe, en vez de un error de Postgres."""
    try:
        return uuid.UUID(project_id)
    except ValueError:
        return None


def _version(row: dict[str, Any]) -> Version:
    return Version(
        number=row["number"],
        origin=row["origin"],
        parent=row["parent_number"],
        note=row["note"],
        created_at=_iso(row["created_at"]),
        model=row.get("model"),
    )


def _project(row: dict[str, Any], versions: list[Version]) -> Project:
    return Project(
        id=str(row["id"]),
        name=row["name"],
        sample=row["sample_id"],
        created_at=_iso(row["created_at"]),
        versions=versions,
        owner=str(row["owner_id"]) if row["owner_id"] is not None else None,
        repo_full_name=row.get("repo_full_name"),
        branch=row.get("branch"),
    )


def _scenario(row: dict[str, Any]) -> ProjectScenario:
    # numeric llega como Decimal
    return ProjectScenario(
        name=row["name"],
        multiplier=float(row["multiplier"]) if row["multiplier"] is not None else None,
        rps=float(row["rps"]) if row["rps"] is not None else None,
        description=row["description"],
    )


def _goals(row: dict[str, Any]) -> ProjectGoals:
    def num(v: Any) -> float | None:
        return float(v) if v is not None else None  # numeric de Postgres llega como Decimal

    return ProjectGoals(num(row["slo_p95_ms"]), num(row["slo_error_rate"]), num(row["budget_usd_month"]))


class PostgresProjectStore:
    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    @classmethod
    def from_url(cls, database_url: str, max_size: int = 5) -> PostgresProjectStore:
        # prepare_threshold=None: el pooler de Supabase en modo transacción no soporta prepared statements
        pool = ConnectionPool(
            database_url,
            min_size=1,
            max_size=max_size,
            kwargs={"prepare_threshold": None, "row_factory": dict_row},
            open=True,
        )
        return cls(pool)

    def close(self) -> None:
        self._pool.close()

    def _conn(self) -> Any:
        return self._pool.connection()  # transacción: commit al salir del with, rollback si hay error

    def create(
        self,
        name: str,
        model: dict[str, Any],
        sample: str | None,
        owner: str | None = None,
        source: RepoSource | None = None,
    ) -> Project:
        conn_id = _uuid(source.connection_id) if source else None
        with self._conn() as conn:
            # owner_id referencia auth.users: un usuario que no existe ahí no puede crear proyectos
            row = conn.execute(
                "insert into projects (name, sample_id, version_count, owner_id, repo_connection_id, branch)"
                " values (%s, %s, 1, %s::uuid, %s, %s) returning id, name, sample_id, created_at, owner_id",
                (name, sample, owner, conn_id, source.branch if source else None),
            ).fetchone()
            v1 = conn.execute(
                "insert into model_versions (project_id, number, origin, note, model, commit_sha, created_by)"
                f" values (%s, 1, 'repo', %s, %s, %s, %s::uuid) returning id, {_SUMMARY}",
                (
                    row["id"],
                    source.note if source else "Extraída del repo",
                    Jsonb(model),
                    source.commit_sha if source else None,
                    owner,
                ),
            ).fetchone()
            if source:  # la ingesta que la produjo, con las estadísticas del extractor
                conn.execute(
                    "insert into ingestions (project_id, repo_connection_id, branch, commit_sha, status, stage,"
                    " stats, model_version_id, started_at, finished_at)"
                    " values (%s, %s, %s, %s, 'done', 'preparacion', %s, %s, now(), now())",
                    (row["id"], conn_id, source.branch, source.commit_sha, Jsonb(source.stats), v1["id"]),
                )
            with conn.cursor() as cur:
                cur.executemany(
                    "insert into scenarios (project_id, name, multiplier, rps) values (%s, %s, %s, %s)",
                    [(row["id"], s.name, s.multiplier, s.rps) for s in scenarios_from_model(model)],
                )
        # el returning no trae el repo (está en repo_connections): sale del source, igual que get y list
        repo = {"repo_full_name": source.repo_full_name, "branch": source.branch} if source else {}
        return _project({**row, **repo}, [_version(v1)])

    def get(self, project_id: str, owner: str | None = None) -> Project | None:
        pid = _uuid(project_id)
        if pid is None:
            return None
        with self._conn() as conn:
            # el proyecto de otro usuario no existe para este (la ruta responde 404, no 403)
            row = conn.execute(
                f"select {_PROJECT_WITH_REPO} where p.id = %s and p.owner_id is not distinct from %s::uuid",
                (pid, owner),
            ).fetchone()
            if row is None:
                return None
            return _project(row, self._summaries(conn, [pid])[pid])

    def get_version(self, project_id: str, number: int) -> Version | None:
        pid = _uuid(project_id)
        if pid is None:
            return None
        with self._conn() as conn:
            row = conn.execute(
                f"select {_SUMMARY}, model from model_versions where project_id = %s and number = %s", (pid, number)
            ).fetchone()
        return _version(row) if row is not None else None

    def list(self, owner: str | None = None) -> list[Project]:
        with self._conn() as conn:
            rows = conn.execute(
                f"select {_PROJECT_WITH_REPO} where p.owner_id is not distinct from %s::uuid"
                " order by p.created_at desc",
                (owner,),
            ).fetchall()
            versions = self._summaries(conn, [r["id"] for r in rows])
        return [_project(r, versions[r["id"]]) for r in rows]

    def add_version(
        self, project_id: str, model: dict[str, Any], origin: Origin, parent: int | None, note: str | None
    ) -> Version:
        pid = _uuid(project_id)
        with self._conn() as conn:
            # numerar sin carreras: el UPDATE bloquea la fila del proyecto hasta el commit
            counted = conn.execute(
                "update projects set version_count = version_count + 1, updated_at = now()"
                " where id = %s returning version_count",
                (pid,),
            ).fetchone()
            if counted is None:
                raise KeyError(project_id)
            row = conn.execute(
                "insert into model_versions (project_id, number, parent_number, origin, note, model)"
                f" values (%s, %s, %s, %s::version_origin, %s, %s) returning {_SUMMARY}, model",
                (pid, counted["version_count"], parent, origin, note, Jsonb(model)),
            ).fetchone()
        return _version(row)

    def list_scenarios(self, project_id: str) -> list[ProjectScenario]:
        pid = _uuid(project_id)
        if pid is None:
            return []
        with self._conn() as conn:
            rows = conn.execute(
                "select name, multiplier, rps, description from scenarios where project_id = %s order by name",
                (pid,),
            ).fetchall()
        return [_scenario(r) for r in rows]

    def upsert_scenario(self, project_id: str, scenario: ProjectScenario) -> ProjectScenario:
        pid = _uuid(project_id)
        with self._conn() as conn:
            if pid is None or conn.execute("select 1 from projects where id = %s", (pid,)).fetchone() is None:
                raise KeyError(project_id)
            row = conn.execute(
                "insert into scenarios (project_id, name, multiplier, rps, description) values (%s, %s, %s, %s, %s)"
                " on conflict (project_id, name) do update set multiplier = excluded.multiplier,"
                " rps = excluded.rps, description = excluded.description"
                " returning name, multiplier, rps, description",
                (pid, scenario.name, scenario.multiplier, scenario.rps, scenario.description),
            ).fetchone()
        return _scenario(row)

    def get_goals(self, project_id: str) -> ProjectGoals:
        pid = _uuid(project_id)
        if pid is None:
            return ProjectGoals()
        with self._conn() as conn:
            row = conn.execute(
                "select slo_p95_ms, slo_error_rate, budget_usd_month from projects where id = %s", (pid,)
            ).fetchone()
        return _goals(row) if row else ProjectGoals()

    def set_goals(self, project_id: str, goals: ProjectGoals) -> ProjectGoals:
        pid = _uuid(project_id)
        with self._conn() as conn:
            row = None
            if pid is not None:
                row = conn.execute(
                    "update projects set slo_p95_ms = %s, slo_error_rate = %s, budget_usd_month = %s,"
                    " updated_at = now() where id = %s returning slo_p95_ms, slo_error_rate, budget_usd_month",
                    (goals.slo_p95_ms, goals.slo_error_rate, goals.budget_usd_month, pid),
                ).fetchone()
            if row is None:
                raise KeyError(project_id)
        return _goals(row)

    def find_run(self, cache_key: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute("select result from runs where cache_key = %s", (cache_key,)).fetchone()
        return row["result"] if row is not None else None

    def save_run(
        self,
        project_id: str,
        number: int,
        cache_key: str,
        params: dict[str, Any],
        run: dict[str, Any],
        engine_version: str,
    ) -> None:
        """Una fila en ``runs`` con el ``Run`` completo y sus métricas en columnas (para listar sin
        leer el JSON). Dos requests iguales a la vez simulan las dos; la segunda no inserta nada."""
        pid = _uuid(project_id)
        with self._conn() as conn:
            version = conn.execute(
                "select id from model_versions where project_id = %s and number = %s", (pid, number)
            ).fetchone()
            if version is None:
                raise KeyError(f"{project_id} v{number}")
            conn.execute(
                "insert into runs (project_id, model_version_id, scenario_id, scenario_name, seed, params,"
                " engine_version, cache_key, result, p95_ms, error_rate, throughput_rps, bottleneck_resource,"
                " elapsed_ms)"
                " values (%s, %s, (select id from scenarios where project_id = %s and name = %s), %s, %s, %s,"
                " %s, %s, %s, %s, %s, %s, %s, %s)"
                " on conflict (cache_key) do nothing",
                (
                    pid,
                    version["id"],
                    pid,
                    run["scenario"],
                    run["scenario"],
                    run["seed"],
                    Jsonb(params),
                    engine_version,
                    cache_key,
                    Jsonb(run),
                    run["latency"]["p95_ms"],
                    run["error_rate"],
                    run["throughput_rps"],
                    run["bottleneck"]["resource"],
                    run["elapsed_ms"],
                ),
            )

    @staticmethod
    def _summaries(conn: Connection, project_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[Version]]:
        by_project: dict[uuid.UUID, list[Version]] = {pid: [] for pid in project_ids}
        if project_ids:
            rows = conn.execute(
                f"select project_id, {_SUMMARY} from model_versions where project_id = any(%s)"
                " order by project_id, number",
                (project_ids,),
            ).fetchall()
            for r in rows:
                by_project[r["project_id"]].append(_version(r))
        return by_project

    # ---------- GitHub App (JAJ-57) ----------

    def save_installation(self, installation_id: int, owner: str | None, account_login: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "insert into github_installations (installation_id, owner_id, account_login)"
                " values (%s, %s::uuid, %s) on conflict (installation_id) do update"
                " set owner_id = excluded.owner_id, account_login = excluded.account_login, revoked_at = null",
                (installation_id, owner, account_login),
            )

    def list_installations(self, owner: str | None) -> list[GitHubInstallation]:
        with self._conn() as conn:
            rows = conn.execute(
                "select installation_id, account_login from github_installations"
                " where owner_id is not distinct from %s::uuid and revoked_at is null order by created_at",
                (owner,),
            ).fetchall()
        return [GitHubInstallation(r["installation_id"], r["account_login"]) for r in rows]

    def revoke_installation(self, installation_id: int) -> None:
        with self._conn() as conn:
            conn.execute(
                "update github_installations set revoked_at = now() where installation_id = %s", (installation_id,)
            )

    def connect_repo(
        self, owner: str | None, installation_id: int, repo_id: int, full_name: str, default_branch: str
    ) -> str:
        with self._conn() as conn:
            row = conn.execute(
                "insert into repo_connections"
                " (owner_id, kind, github_installation_id, github_repo_id, repo_full_name, default_branch)"
                " values (%s::uuid, 'github', %s, %s, %s, %s)"
                " on conflict (owner_id, github_repo_id) where kind = 'github' do update"
                " set github_installation_id = excluded.github_installation_id,"
                " repo_full_name = excluded.repo_full_name, default_branch = excluded.default_branch,"
                " revoked_at = null returning id",
                (owner, installation_id, repo_id, full_name, default_branch),
            ).fetchone()
        return str(row["id"])
