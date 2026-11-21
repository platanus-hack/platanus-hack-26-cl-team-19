# Backend de Branchpoint

Contiene el **motor de simulación** (JAJ-14) y la **API** que lo expone al editor (JAJ-49, JAJ-52). El modelo de datos persistente está definido en `app/db` (JAJ-55) y lo implementa JAJ-56. Para levantar la base de datos local, ver [`docs/supabase-local.md`](../docs/supabase-local.md).

## Estructura

```
backend/
├── pyproject.toml           # dependencias (FastAPI y uvicorn para la API; el motor solo usa la librería estándar)
├── app/
│   ├── api/                 # API HTTP (FastAPI)
│   │   ├── main.py          #   arma la app: CORS, errores y rutas
│   │   ├── schemas.py       #   lo que recibe y devuelve cada ruta
│   │   ├── errors.py        #   formato de los errores ({"error": {"code", "message"}})
│   │   ├── store.py         #   interfaz ProjectStore y su versión en memoria
│   │   └── routes/          #   rutas por tema: health, runs, models, projects
│   ├── models/              # estructuras de datos
│   │   ├── architecture.py  #   entrada: el modelo branchpoint.model/v1 (JAJ-45) y load_model()
│   │   ├── run.py           #   salida: el Run (branchpoint.run/v1)
│   │   ├── graph.py         #   grafo del diagrama (nodos y aristas) desde el modelo
│   │   └── compare.py       #   delta entre dos Run y cambios entre dos modelos
│   ├── engine/              # motor de eventos discretos
│   │   ├── kernel.py        #   reloj, cola de eventos y recursos (genérico)
│   │   ├── simulate.py      #   arma los recursos desde el modelo y recorre los pasos de cada request
│   │   └── metrics.py       #   percentiles y series por segundo
│   ├── agent/               # lo que usa el agente de IA (ADR 0001)
│   │   └── ops.py           #   operaciones tipadas que proponen versiones (JAJ-68)
│   ├── catalog/             # catálogo de números con procedencia (copia de spikes/jaj-45-numeros/catalog.json)
│   ├── samples/             # modelos de ejemplo que sirve GET /models (salida de JAJ-45)
│   ├── db/                  # modelo de datos (JAJ-55) y ProjectStore sobre Postgres (JAJ-56)
│   └── cli.py               # correr una simulación desde la terminal
└── tests/
    ├── fixtures/            # versión fija del modelo del template (anterior a JAJ-47) para los tests del motor
    ├── engine/              # tests del kernel y del motor
    ├── agent/               # tests de las operaciones
    └── api/                 # tests de la API
```

El flujo es: **modelo v1 (JSON)** → `load_model()` → `simulate()` → **Run**. La API recibe el modelo en `POST /runs` y devuelve el `Run`.

## Cómo modela el sistema el motor

Los recursos se arman desde el `deployment` del modelo:

| Recurso | Capacidad | Qué lo ocupa |
| -- | -- | -- |
| CPU de la API (`api_cpu`) | `min(workers, vCPU) × réplicas` núcleos | CPU base de cada request y pasos de CPU (ej. hash de contraseña) |
| Hilos de la API (`api_threads`) | hilos por worker × workers × réplicas | endpoints `def` (síncronos), durante toda la request |
| Pool de conexiones (`db_pool`) | pool por worker × workers × réplicas (tope: conexiones de la DB) | desde la primera consulta hasta el final de la request |
| CPU de la DB (`db_cpu`) | vCPU de la DB | cada consulta, durante su tiempo (también las de los workers de las colas) |
| Workers de una cola (`queue:<nombre>`) | `workers` de la cola | cada trabajo encolado, durante sus `job_steps` |

- Cada request recorre los `steps` de su endpoint en orden. Respeta `repeat` (N+1).
- Esperar una conexión más que el timeout del pool es un error (`pool_timeout`).
- **Límite de conexiones de la DB.** Sin pooler, si la app puede abrir más conexiones que las que acepta la DB, la que pasa el límite falla al conectarse (`db_refused`), como el `too many clients` de Postgres. Con un pooler en modo transacción (`deployment.db.pooler`, por ejemplo Supavisor de Supabase), la app se conecta al pooler, que acepta `client_connections` y los reparte en las `max_connections` de la DB: los que no tienen una, esperan. Si la app pasa también el límite del pooler, vuelve a ser `db_refused`.
- Tardar más que el timeout del cliente (30 s por defecto) también es un error (`client_timeout`). Aun así, el servidor hace el trabajo, como se vio en JAJ-9.
- Con vCPU fraccionarios, por ejemplo 0,5 en Supabase Micro, se simula 1 núcleo que tarda el doble.

### Caché y colas

Son campos opcionales del modelo. `build_model.py` (JAJ-45) todavía no los genera: sin ellos, la caché y el encolar son solo una espera, igual que antes.

```jsonc
// paso de caché: GET; si acierta, se salta on_miss; si falla, hace on_miss y luego SET
{"kind": "cache", "resource": "cache", "time": {"value": 0.03}, "hit_ratio": {"value": 0.8},
 "on_miss": [{"kind": "db", "resource": "db_connection", "time": {"value": 20}}]}

// paso que encola un trabajo
{"kind": "background", "resource": "background", "time": {"value": 0.03}, "queue": "emails"}

// deployment.queues: workers asíncronos (Celery, RQ, arq...)
"queues": {"emails": {"workers": {"value": 2}, "max_length": {"value": 1000},
                      "job_steps": [{"kind": "external", "resource": "external", "time": {"value": 300}}]}}
```

- Sin `hit_ratio`, la caché se simula con 0 % de aciertos (el peor caso) y el modelo lo advierte. `--cache-hit` en el CLI, o `cache_hit_ratio` en `simulate()`, reemplaza la tasa de todas las cachés.
- Si hay una sola cola, los pasos `background` sin `queue` usan esa. Si no tienen cola, solo se simula el encolar y el modelo lo advierte.
- La request no espera al trabajo. El trabajo espera un worker libre y usa su propia conexión a la DB, no el pool de la API. Sus consultas sí ocupan la CPU de la DB.
- Si la cola está en su `max_length`, encolar falla y la request termina con error `queue_full`. Sin `max_length`, la cola crece sin límite.
- El `Run` trae `cache` (aciertos y fallos) y `queues` (encolados, procesados, rechazados, cola al final y latencia de los trabajos).

### De laptop a nube (JAJ-48)

Los tiempos de CPU del modelo (CPU de la API, hash de contraseña y consultas) se midieron en 1 núcleo del laptop de calibración (JAJ-46). Un vCPU de la nube es más lento, así que el motor los ajusta con dos campos del modelo, que genera `build_model.py` desde JAJ-47:

| Campo del modelo | Qué hace el motor | Ejemplo |
| -- | -- | -- |
| `deployment.api.cpu_core_factor` | Multiplica la CPU base y los pasos de CPU de cada request | Fargate ARM (Graviton2): ×1,95 |
| `deployment.db.cpu_core_factor` | Multiplica el tiempo de cada consulta. La conexión también se retiene ese tiempo extra | Supabase y `db.t4g.*` (Graviton2): ×1,95 |
| `deployment.db.cpu_credits.sustained_vcpu` | En instancias con créditos de CPU, simula la DB con esos vCPU | `db.t4g.medium`: 2 vCPU, base de 20 % → 0,4 vCPU |

- **La capacidad baja en el factor:** con factor 1,55, el sistema satura a 1/1,55 de las req/s que aguantaba en el laptop.
- **Créditos de CPU:** con `cpu_credits` (`--cpu-credits` en el CLI, o el campo del body de `POST /runs`) se elige el caso.
  - `sustained`, el valor por defecto, usa la base de créditos. Es lo que aguanta la instancia con carga sostenida, como un CyberDay de horas.
  - `burst` usa todos los vCPU. Solo se mantiene mientras duren los créditos, o pagando el exceso.
- **Sin estos campos,** los tiempos se usan tal cual (factor 1), como antes de JAJ-48.
- **Los trabajos de las colas** usan sus tiempos sin ajustar. El modelo todavía no dice en qué procesador corren.
- **El `Run` lo informa:** trae `cpu` (factores, procesadores, vCPU de la DB del plan y los simulados, y el modo de créditos), y una advertencia en `warnings` que dice qué se ajustó.

**Validación del ajuste** (`tests/engine/test_cloud_factor.py`):
- **Cuentas a mano:** el uso de CPU sube exactamente en el factor, y el punto de saturación baja en el factor.
- **Contra los `checks` de `build_model.py`, que ya aplican el factor y la base de créditos:** en los dos modelos de ejemplo, el motor da el mismo uso de CPU (±5 %) en los escenarios bajo saturación, y el mismo cuello de botella en CyberDay.

### Quién causa el cuello de botella (JAJ-69)

Cada vez que una request suelta un recurso, el motor anota cuánto tiempo lo tuvo, a nombre de su endpoint y de la línea de código del paso que lo ocupó (el `at` del paso):

| Recurso | Línea a la que se anota |
| -- | -- |
| CPU de la API | la del paso de CPU (ej. el hash de contraseña). La CPU propia del framework no tiene línea |
| CPU de la DB | la de cada consulta |
| Pool de conexiones | la de la consulta que tomó la conexión, que se retiene hasta el final de la request |
| Hilos de la API | ninguna: se toman por toda la request (endpoints `def`) |
| Workers de una cola | ninguna. El dueño es `cola <nombre>` |

Con eso, el `Run` dice quién ocupa cada recurso:

- **`resources[].by_endpoint`:** cada endpoint, con su fracción del tiempo ocupado (`share`, entre todos suman 1) y sus líneas en ese recurso (`refs`).
- **`resources[].by_line`:** cada línea, sumando todos los endpoints que pasan por ella. Sirve cuando el problema está en código compartido, por ejemplo una función que usan muchos endpoints.
- **`bottleneck.line`, `line_share` y `line_endpoints`:** la línea que más ocupa el recurso saturado. Es lo que muestra el banner del editor.
- **`bottleneck.endpoint`, `endpoint_share` y `refs`:** el endpoint que más ocupa el recurso saturado, y sus líneas.
- **`bottleneck.message`:** nombra las dos cosas. Ejemplo con el template en CyberDay: *"CPU de la API al 100 %… El 58 % se va en `backend/app/core/security.py:36` (6 endpoints). El endpoint que más lo ocupa es `PATCH /users/me/password` (18 %)."*

Los tests están en `tests/engine/test_attribution.py`:
- **Reparto:** con 8 ms contra 2 ms de CPU, el reparto es 80 % y 20 %.
- **Línea compartida:** se suma entre los endpoints que la usan.
- **Pool:** se anota a la primera consulta de la request.
- **Hilos y colas:** se anotan a la request completa y a la cola.
- **Template:** en CyberDay, el cuello de botella apunta a una línea de hash de contraseña con más del 50 % de la CPU.

**Validación:** el modelo se validó contra un sistema real en JAJ-9, JAJ-43, JAJ-42 y JAJ-44. Acierta la saturación con 0–11 % de error. Cerca o sobre la capacidad es optimista, así que el `Run` lo advierte cuando un recurso pasa el 90 %. La caché reproduce la prueba de JAJ-44: con 50 % de aciertos, el p95 queda entre −8 % y +6 % de lo medido hasta el 89 % de uso del pool. Al 99 % el motor da el doble (es pesimista ahí) (`tests/engine/test_cache_queue.py`).

## Cómo usarlo

Con Python 3.12 o más nuevo (en Linux, macOS o WSL), desde `backend/`:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# tests
python -m pytest -q

# simular CyberDay ×20 con el modelo de ejemplo (guarda el Run completo con --out)
python -m app.cli app/samples/full-stack-fastapi-template.model.json --scenario cyberday --out run.json

# la DB de realworld es un db.t4g.medium: comparar con sus vCPU sostenidos (por defecto) y en burst
python -m app.cli app/samples/fastapi-realworld-example-app.model.json --scenario pico_normal --cpu-credits burst

# levantar la API en http://localhost:8000 (documentación interactiva en /docs)
uvicorn app.api.main:app --reload

# lo mismo, guardando los proyectos en el Supabase local (ver docs/supabase-local.md)
uvicorn app.api.main:app --reload --env-file .env

# tests, incluidos los de Postgres (con el Supabase local arriba)
TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres python -m pytest -q
```

Sin instalar Python, con Docker (en Git Bash de Windows, antepongan `MSYS_NO_PATHCONV=1` y usen `$(pwd -W)` en vez de `$PWD`):

```bash
docker run --rm -v "$PWD:/w" -w /w python:3.14-slim sh -c 'pip install -q -e ".[dev]" && python -m pytest -q'
```

### API

| Método | Ruta | Qué hace |
| -- | -- | -- |
| `GET` | `/health` | Revisa que la API está arriba. |
| `POST` | `/runs` | Simula un modelo y devuelve el `Run` (`branchpoint.run/v1`). No guarda nada (eso es JAJ-56). |
| `GET` | `/models` | Modelos de ejemplo para abrir el editor sin ingerir un repo: id, repo, despliegue y req/s de cada escenario. |
| `GET` | `/models/{id}` | Un modelo de ejemplo completo (`branchpoint.model/v1`). |
| `POST` | `/graph` | Grafo del diagrama desde `{"model": ...}`: nodos, aristas con sus endpoints y `archivo:línea`, y el peso de cada endpoint. |
| `POST` | `/projects` | Crea un proyecto desde `{"sample": id}` o `{"model": ...}`, con `name` opcional. Queda con **v1** (`origin: repo`). |
| `GET` | `/projects` · `/projects/{id}` | Los proyectos, o uno con su historial de versiones (sin los modelos). |
| `POST` | `/projects/{id}/versions` | Guarda `{"model", "origin", "parent", "note"}` como versión nueva. `origin`: `repo`, `manual` (por defecto) o `agente`; `parent`: por defecto, la última. |
| `GET` | `/projects/{id}/versions/{n}` | Una versión con su modelo. |
| `POST` | `/projects/{id}/versions/{n}/runs` | Simula la versión `n`. Body: el de `POST /runs` sin `model`. |
| `POST` | `/projects/{id}/versions/{n}/ops` | Aplica `{"ops": [...], "note"}` a la versión `n` y guarda el resultado como versión nueva (`origin: agente`, antecesora `n`). Devuelve la versión con `changes` (una línea por operación) y `warnings`. Ver "Operaciones" abajo. |
| `POST` | `/projects/{id}/compare` | Simula las versiones `a` y `b` con el mismo escenario y semilla. Devuelve los dos `Run` y `delta`: p50/p95/p99, errores y throughput (`a`, `b`, `diff`, `pct`), si cambió el cuello de botella y `model_changes` (qué valores cambiaron entre los modelos). |

**Dónde se guardan los proyectos:** con `DATABASE_URL` (en `backend/.env`), en Postgres (`app/db/postgres_store.py`). Sin ella, en memoria, y se pierden al reiniciar la API. Las dos implementan `ProjectStore` (`app/api/store.py`), así que las rutas son las mismas. Con Postgres, los ids de proyecto son `uuid`.

```bash
# abrir el editor con v1, guardar una v2 y comparar
P=$(curl -s -H "Content-Type: application/json" -d '{"sample": "full-stack-fastapi-template"}' localhost:8000/projects | python -c 'import json,sys; print(json.load(sys.stdin)["id"])')
curl -s localhost:8000/projects/$P/versions/1 | python -c 'import json,sys; m = json.load(sys.stdin)["model"]; m["deployment"]["api"]["replicas"]["value"] = 4; print(json.dumps({"model": m, "note": "API ×4"}))' > v2.json
curl -s -H "Content-Type: application/json" --data @v2.json localhost:8000/projects/$P/versions
curl -s -H "Content-Type: application/json" -d '{"a": 1, "b": 2, "scenario": "cyberday"}' localhost:8000/projects/$P/compare
```

Body de `POST /runs`. Solo `model` es obligatorio:

```jsonc
{
  "model": { "schema": "branchpoint.model/v1", ... },  // el modelo completo (salida de build_model.py)
  "scenario": "cyberday",       // un escenario de traffic.scenarios
  "rps": null,                  // reemplaza las req/s del escenario; con rps, el escenario es solo un nombre
  "seed": 0,                    // misma semilla = mismo resultado
  "duration_s": 60,             // segundos simulados (máximo 3600)
  "arrivals": "poisson",        // o "uniform" (tasa constante, como k6)
  "client_timeout_s": 30,       // null = sin timeout
  "cache_hit_ratio": null,      // reemplaza la tasa de aciertos de las cachés con on_miss
  "cpu_credits": "sustained"    // DB con créditos de CPU (db.t4g.*): "sustained" (vCPU sostenidos) o "burst" (todos)
}
```

```bash
# ejemplo: armar el body con el modelo de ejemplo y simular CyberDay
python -c 'import json; m = json.load(open("tests/fixtures/full-stack-fastapi-template.model.json")); print(json.dumps({"model": m, "scenario": "cyberday"}))' > req.json
curl -s -H "Content-Type: application/json" --data @req.json localhost:8000/runs
```

Los errores responden 422 (o 404 si algo no existe) con `{"error": {"code", "message", ...}}`. El `message` está en español y está pensado para mostrarlo tal cual:

| `code` | Cuándo |
| -- | -- |
| `invalid_model` | El modelo no es `branchpoint.model/v1` o le falta un campo. |
| `unknown_scenario` | El escenario no está en el modelo. Trae `available` con los que hay. |
| `invalid_parameters` | Un parámetro está fuera de rango, falta o sobra. Trae `fields` con cada campo. |
| `run_too_large` | Tasa × duración pasa las 300.000 requests (unos pocos segundos de cálculo). |
| `invalid_operations` | Una operación de `/ops` no se puede aplicar. El `message` dice cuál y qué valores sí existen. No guarda nada. |
| `not_found` | 404: el modelo de ejemplo, proyecto o versión no existe. Trae `resource` (`model`, `project` o `version`). |

- **CORS:** por defecto acepta llamadas desde el Nuxt de desarrollo (`http://localhost:3000`). Para otros orígenes, usen `BRANCHPOINT_CORS_ORIGINS`, separados por coma.
- **La simulación ocupa CPU:** por eso la ruta es `def` y no `async def`. FastAPI la corre en su pool de hilos y no bloquea las demás requests mientras simula.

### Operaciones

Son el vocabulario con que el agente propone versiones (`app/agent/ops.py`, [ADR 0001](../docs/adr/0001-el-llm-opera-sobre-el-modelo-no-lo-extrae.md)): el LLM nunca edita el JSON del modelo. Cada operación valida sus argumentos, se aplica sobre una copia y el resultado tiene que cargar en el motor.

| Operación | Qué cambia | De dónde salen los números |
| -- | -- | -- |
| `scale_api(replicas, vcpu?, quote?)` | Réplicas y vCPU de la API; recalcula `usd_month` | Decisión de diseño: `SUPUESTO` "Propuesta del agente" con `needs_review`, o la frase del usuario si va `quote`. Precio de Fargate del catálogo |
| `change_db_plan(plan, provider?)` | vCPU, conexiones, procesador, créditos de CPU, pooler y costo | Plan del catálogo (JAJ-11) |
| `add_pooler()` | Agrega `deployment.db.pooler` en modo transacción | `pooler_connections` del plan. Solo Supabase en el MVP |
| `add_cache(endpoint, at?, hit_ratio?, quote?)` | Las lecturas del endpoint GET pasan a `on_miss` de un paso de caché | Tiempo de Redis del catálogo. `hit_ratio` es un dato del usuario: solo con `quote`; sin él, 0 % de aciertos (el peor caso) |
| `move_to_queue(endpoint, at, queue, workers, quote?)` | El paso de `at` pasa a `job_steps` de una cola nueva y la request solo encola | Tiempo de encolar del catálogo. `workers`: decisión de diseño, igual que `replicas` |

Después de aplicar, se borran las `checks` (las cotas de `build_model.py` eran de la versión original) y se recalculan los `assumptions`. El costo de Redis y de los workers de las colas todavía no está en el modelo: las operaciones lo advierten en `warnings`.

```bash
# v2 propuesta: 3 réplicas + pooler, y compararla con v1 en CyberDay
curl -s -H "Content-Type: application/json" -d '{"ops": [{"op": "scale_api", "replicas": 3}, {"op": "add_pooler"}]}' localhost:8000/projects/$P/versions/1/ops
curl -s -H "Content-Type: application/json" -d '{"a": 1, "b": 2, "scenario": "cyberday"}' localhost:8000/projects/$P/compare
```

Desde Python:

```python
from app.models import load_model
from app.engine import simulate

run = simulate(load_model("modelo.json"), "cyberday", seed=0, duration_s=60)
print(run.bottleneck.message)
run.to_dict()  # listo para JSON
```
