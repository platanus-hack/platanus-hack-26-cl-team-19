# IA-5: Varios repos por proyecto

**Área:** backend, DB · **Depende de:** IA-3 · **Tamaño:** L · **Bloquea:** IA-10

## Objetivo

Que un proyecto se cree a partir de hasta 4 repos. El agente analiza cada uno. El motor simula el principal y los demás aparecen en el diagrama como servicios que no se simulan.

## Leer antes

* `backend/app/github/ingestion.py`: `run_ingestion`, `model_from_tarball`.
* `backend/app/ingest/analyzer.py`: `analyze_repo` analiza **un** repo y devuelve un `ArchitectureSubmission`.
* `backend/app/ingest/ai_graph.py`: `build_from_ai`, `AiComponent`, `_services`.
* `backend/app/models/graph.py`: `build_graph`, de donde sale el diagrama (`POST /graph`).
* `backend/app/api/store.py`: `RepoSource`, `ProjectStore.create`.
* `backend/tests/api/test_project_repositories.py` y `GET /projects` (JAJ-92): qué se guarda hoy de los repos.

## Diseño

Un análisis por repo, no un agente que lea todos a la vez. `analyze_repo` y su schema no cambian, los análisis corren en paralelo y un repo que falla no bota a los otros.

```
repos[] ──▶ por cada uno: tarball ─▶ analyze_repo ─▶ ArchitectureSubmission
                                                          │
principal ─▶ build_from_ai(sub, iac, root) ─▶ model/v1 ◀──┘
secundarios ─▶ un servicio por repo en deployment.services (no simulado)
```

## Cambios

### 1. API

`POST /github/ingestions` acepta el cuerpo de hoy y además:

```json
{
  "repos": [{"full_name": "org/api", "branch": "main"}, {"full_name": "org/worker", "branch": "main"}],
  "name": "Tienda",
  "provider": "anthropic",
  "primary": "org/api"
}
```

* `repos`: entre 1 y 4, sin repetidos. El cuerpo con `repo_full_name` sigue funcionando y equivale a un solo repo.
* `primary`: obligatorio con más de un repo y tiene que estar en `repos`. Si no, 422.
* Cada repo analizado descuenta 1 de la cuota de extracción (IA-2). Se descuentan todos al encolar: si no alcanza para todos, 429 y no se encola ninguno.

### 2. Trabajo de ingesta

* Descargar y analizar los repos en paralelo, con un `ThreadPoolExecutor` de hasta 4 hilos. Cada repo tiene su carpeta temporal y su instancia de `LLM`.
* Si falla el **principal** (`NoEndpoints`, `AnalysisFailed`, error de GitHub): la ingesta termina `failed`.
* Si falla un **secundario**: la ingesta sigue. El repo queda en `warnings` del modelo con el motivo y aparece en el diagrama como un servicio sin detalle.
* `Ingestion` gana `repos: list[RepoProgress]` con `full_name`, `status` (`queued`, `running`, `done`, `failed`), `endpoints` y `llm_steps`. Los campos de un solo repo que ya existen se mantienen y reflejan el principal.
* El tope de tokens de IA-4, si existe, es por repo.

### 3. Modelo

El modelo `model/v1` sale del principal con `build_from_ai`, como hoy. Después se le agregan los secundarios:

* Por cada repo secundario, una entrada en `deployment.services` con `name` (nombre del repo), `role: "service"`, `repo`, `technology` (el `framework` del análisis), `endpoints` (cantidad), `origin` como el resto de los componentes de IA y `simulated: false`.
* Los componentes de un secundario (su DB, su caché) se agregan también, con `repo` y `simulated: false`. Si el principal ya tiene un componente con el mismo nombre y rol, se considera el mismo y no se duplica.
* **Enlaces entre repos.** Si un paso externo del principal nombra a un secundario (comparar `detail` y el nombre del componente externo con el nombre del repo, sin el dueño y sin distinguir mayúsculas), ese componente externo se reemplaza por el servicio del secundario. El paso sigue simulándose como `external`, con el tiempo del catálogo. Lo que no calza queda como externo: no adivinar.
* `model["repo"]["sources"]`: lista con `full_name`, `branch`, `commit`, `analysis` (modelo, proveedor, tokens) y `primary`. `model["repo"]["source"]` se mantiene con el principal.
* Revisar que `load_model` de `app/models/architecture.py` ignore las claves nuevas y que `simulate` corra igual.

En `app/models/graph.py`, `build_graph` pasa `repo` y `simulated` a los nodos. Los nodos de un modelo de un solo repo quedan con `simulated: true` donde corresponde y sin cambios en lo demás.

### 4. Persistencia

* `ProjectStore.create` acepta `sources: list[RepoSource]`. Mirar primero cómo se guarda hoy el repo del proyecto (JAJ-92). Si es una sola referencia a `repo_connections`, agregar por migración `project_repositories (project_id, repo_connection_id, branch, commit_sha, is_primary)` y dejar la referencia actual apuntando al principal.
* `GET /projects` mantiene `repo` (el principal) y agrega `repos`.
* Implementarlo en el store Postgres y en el de memoria.

## Criterios de aceptación

Con un LLM falso que responde distinto según el repo:

* Dos repos: la ingesta termina `done`, el modelo simula los endpoints del principal y `deployment.services` trae el secundario con `simulated: false`.
* Un paso externo del principal que nombra al secundario queda enlazado a su servicio. Uno que no calza queda como externo.
* El secundario falla con `AnalysisFailed`: la ingesta termina `done` con un aviso. El principal falla: `failed`.
* `primary` ausente con dos repos, o fuera de la lista: 422. Cinco repos: 422.
* Cuota: con 1 análisis disponible y 2 repos, 429 y la cuota no cambia.
* Regresión: el cuerpo antiguo con un solo repo produce el mismo modelo que antes de esta PR, salvo `repo.sources`.
* `GET /projects` devuelve `repo` y `repos`.
* `POST /graph` de un modelo con dos repos devuelve los dos servicios, con `repo` y `simulated`.
* La key no aparece en ningún campo del trabajo.

## Fuera de alcance

* Simular más de un servicio.
* Un agente que lea varios repos a la vez para descubrir enlaces que no están en los nombres.
* Volver a analizar un repo cuando cambia.
* Subir un `.zip`.
