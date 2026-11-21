# IA-5: Ingesta con IA y varios repos

**Área:** backend, DB · **Depende de:** IA-2, IA-3, IA-4 · **Tamaño:** L · **Bloquea:** IA-10

## Objetivo

Que `POST /github/ingestions` acepte uno o más repos de cualquier tecnología, elija el extractor, arme el modelo desde `graph/v1` y guarde el grafo junto al proyecto.

## Leer antes

* `backend/app/github/ingestion.py`: `run_ingestion`, `model_from_tarball`, `IngestionJobs`.
* `backend/app/api/routes/github.py`: `start_ingestion`.
* `backend/app/ingest/build_model.py`: `build()`, `read_workers`, `read_pool`, `build_endpoint`, `deployment_model`.
* `backend/app/api/store.py`: `RepoSource`, `ProjectStore.create`.
* `backend/app/db/schema.sql`: `ingestions`, `model_versions`, `projects`.

## Cambios

### 1. `build_model` consume un `Graph`

Separar `build()` en dos:

* `build_from_graph(graph: Graph, roots: dict[str, Path], answers: dict, primary: str | None = None) -> dict`: arma `model/v1`.
* `build(repo, answers)`: queda como envoltorio para la CLI. Corre `extract.run`, `from_ast` y llama a `build_from_graph`.

Dentro de `build_from_graph`:

* **Servicio principal.** El motor simula un solo servicio. Es `primary` si viene; si no, el `service` con más endpoints. Solo sus endpoints entran a `model["endpoints"]`.
* **Efectos.** Convertir cada `Effect` del grafo al dict que espera `step_for` (`kind`, `shape`, `detail`, `file`, `line`, `in_loop`, `via`). Un efecto `http` o `sdk` cuyo `target` es otro `service` del grafo queda como paso `external` con `detail` igual al nombre de ese servicio.
* **Procedencia.** Si el endpoint tiene `origin="llm"`, los números derivados quedan como mucho `ESTIMADO` y la fuente agrega "estructura extraída por LLM".
* **Workers y pool.** Si el repo principal es Python, usar `read_workers` y `read_pool` como hoy. Si no, tomar los `ConfigValue` del grafo como `OBSERVADO` con `at`, y lo que falte sale del catálogo como `SUPUESTO` con `needs_review`.
* **Grafo en el modelo.** Agregar `model["graph"] = {"components": [...], "edges": [...], "primary": "<id>", "warnings": [...]}`. Es lo que dibuja el frontend (IA-10). Revisar que `load_model` de `app/models/architecture.py` ignore la clave nueva.
* Sin endpoints en el servicio principal: `NoEndpoints`, con un mensaje que ya no diga "Branchpoint analiza apps FastAPI".

El modelo de un repo FastAPI no debe cambiar salvo por la clave `graph`: hay un test de regresión contra `tests/fixtures/full-stack-fastapi-template.model.json`.

### 2. API

`POST /github/ingestions` acepta el cuerpo de hoy y además:

```json
{
  "repos": [{"full_name": "org/api", "branch": "main"}, {"full_name": "org/worker", "branch": "main"}],
  "project_name": "Tienda",
  "provider": "anthropic",
  "primary": "org/api"
}
```

* `repos`: entre 1 y 4. El cuerpo antiguo, con un solo repo, sigue funcionando.
* Headers opcionales `X-Anthropic-Api-Key` y `X-OpenAI-Api-Key`, igual que el chat.
* La key se resuelve **antes** de encolar, con `llm_key(..., purpose="extract")` de IA-2, y solo si hace falta el LLM (ver punto 3). Así el 429 de cuota llega en la respuesta y no en el trabajo.
* La key no se guarda en `Ingestion` ni en logs: se pasa al trabajo por una clausura.

### 3. Elegir el extractor

Por cada repo, después de descargarlo:

1. Correr `scan_deployment` (siempre) y `extract.run`.
2. Si `extract.run` encuentra endpoints: ese repo queda resuelto con `from_ast`.
3. Si no: ese repo necesita el LLM.

Si ningún repo necesita el LLM, no se pide key ni se descuenta cuota. Como eso no se sabe antes de descargar, la cuota se reserva al encolar y se **devuelve** si no se usó (agregar `refund_team(owner, purpose)` al store).

Si algún repo lo necesita, una sola llamada a `extract_with_llm` con todos los `roots` y como `seed` la unión de los grafos ya resueltos.

Sin key disponible y con repos que la necesitan: el trabajo falla con el mensaje "Este repo no es FastAPI: analizarlo usa IA. Guarda tu API key o usa la cuota de Branchpoint."

### 4. Progreso

* Etapas de `Ingestion`: `acceso`, `analisis`, `extraccion_ia` (nueva, solo si se usa), `preparacion`.
* Campos nuevos en `Ingestion` e `IngestionOut`: `extractor` (`ast`, `llm` o `mixto`), `llm_steps` (vueltas hasta ahora, vía `on_event`), `cost` (el dict de `cost_usd`, al terminar).

### 5. Persistencia

* `RepoSource` hoy describe un repo. `ProjectStore.create` pasa a aceptar `sources: list[RepoSource]`. Revisar cómo `GET /projects` devuelve el repo (JAJ-92) y devolver la lista sin romper el campo actual: mantener `repo` con el principal y agregar `repos`.
* Si `ingestions` o `projects` tienen una sola referencia a `repo_connections`, agregar por migración una tabla `project_repositories (project_id, repo_connection_id, branch, commit_sha, is_primary)`. Hay tests en `tests/api/test_project_repositories.py`: leerlos antes para no duplicar lo que ya exista.
* El grafo va dentro del modelo de la versión 1 (clave `graph`). No hace falta columna nueva.

## Criterios de aceptación

* Regresión: ingerir el fixture FastAPI da el mismo modelo que hoy más la clave `graph`. No se llama al LLM ni se descuenta cuota.
* Con un LLM falso (reemplazando la fábrica en `app.state`, como hace el chat): un repo sin FastAPI termina `done` con `extractor="llm"` y un modelo que `load_model` acepta y `simulate` corre.
* Dos repos, uno FastAPI y uno no: `extractor="mixto"`, el modelo simula el principal y `graph.components` tiene los dos servicios.
* Sin key y con cuota agotada: 429 al encolar. Con repo FastAPI y cuota agotada: funciona.
* La cuota reservada se devuelve si la ingesta no usó el LLM o falló antes de usarlo.
* Un test recorre los eventos y los campos del trabajo y comprueba que la key no aparece.
* El cuerpo antiguo de `POST /github/ingestions` sigue funcionando.

## Fuera de alcance

* Simular más de un servicio.
* Volver a extraer cuando cambia el repo.
* Subir un `.zip` en vez de conectar GitHub.
