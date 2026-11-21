"""``ProjectStore`` sobre Postgres (JAJ-56): proyectos, versiones y escenarios en las tablas de
``supabase/migrations/``. El mapeo de cada método a SQL está en ``app/db/README.md``.

El backend se conecta con ``DATABASE_URL`` como el rol ``postgres``, que no pasa por RLS. Mientras
no haya login (JAJ-57), los proyectos no tienen dueño: ``list()`` muestra los de ``owner_id`` nulo.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from app.api.store import Origin, Project, Version

_SUMMARY = "number, origin::text as origin, parent_number, note, created_at"


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
    )


def _scenario_rates(model: dict[str, Any]) -> list[tuple[str, float | None, float | None]]:
    """Los escenarios del modelo como ``(nombre, multiplier, rps)``, con uno solo de los dos.

    Se guarda el multiplicador cuando lo hay: así la tasa se recalcula con el pico de cada versión
    (decisión 4 del README de ``app/db``).
    """
    rates = []
    for name, sc in (model.get("traffic", {}).get("scenarios") or {}).items():
        multiplier = (sc.get("multiplier") or {}).get("value")
        rps = (sc.get("rps") or {}).get("value")
        if multiplier is not None and multiplier > 0:
            rates.append((name, multiplier, None))
        elif rps is not None and rps > 0:
            rates.append((name, None, rps))
    return rates


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

    def create(self, name: str, model: dict[str, Any], sample: str | None) -> Project:
        with self._conn() as conn:
            row = conn.execute(
                "insert into projects (name, sample_id, version_count) values (%s, %s, 1)"
                " returning id, name, sample_id, created_at",
                (name, sample),
            ).fetchone()
            v1 = conn.execute(
                "insert into model_versions (project_id, number, origin, note, model)"
                f" values (%s, 1, 'repo', 'Extraída del repo', %s) returning {_SUMMARY}",
                (row["id"], Jsonb(model)),
            ).fetchone()
            with conn.cursor() as cur:
                cur.executemany(
                    "insert into scenarios (project_id, name, multiplier, rps) values (%s, %s, %s, %s)",
                    [(row["id"], *rate) for rate in _scenario_rates(model)],
                )
        return _project(row, [_version(v1)])

    def get(self, project_id: str) -> Project | None:
        pid = _uuid(project_id)
        if pid is None:
            return None
        with self._conn() as conn:
            row = conn.execute("select id, name, sample_id, created_at from projects where id = %s", (pid,)).fetchone()
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

    def list(self) -> list[Project]:
        with self._conn() as conn:
            rows = conn.execute(
                "select id, name, sample_id, created_at from projects where owner_id is null order by created_at desc"
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
