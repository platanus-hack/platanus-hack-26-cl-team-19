# Backend de Branchpoint

Contiene el **motor de simulación** (JAJ-14), la **API** que lo expone al editor (JAJ-49, JAJ-52) y el **costo mensual** de cada arquitectura (JAJ-72). El modelo de datos persistente está definido en `app/db` (JAJ-55) y lo implementa JAJ-56. Para levantar la base de datos local, ver [`docs/supabase-local.md`](../docs/supabase-local.md).

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
│   │   ├── run_cache.py     #   runs guardados por cache_key (JAJ-75)
│   │   └── routes/          #   rutas por tema: health, runs, models, projects
│   ├── models/              # estructuras de datos
│   │   ├── architecture.py  #   entrada: el modelo branchpoint.model/v1 (JAJ-45) y load_model()
│   │   ├── run.py           #   salida: el Run (branchpoint.run/v1)
│   │   ├── traffic.py       #   perfil de tráfico en el tiempo y el preset "pico" (JAJ-71)
│   │   ├── graph.py         #   grafo del diagrama (nodos y aristas) desde el modelo
│   │   └── compare.py       #   delta entre dos Run y cambios entre dos modelos
│   ├── engine/              # motor de eventos discretos
│   │   ├── kernel.py        #   reloj, cola de eventos y recursos (genérico)
│   │   ├── simulate.py      #   arma los recursos desde el modelo y recorre los pasos de cada request
│   │   └── metrics.py       #   percentiles y series por segundo
│   ├── agent/               # lo que usa el agente de IA (ADR 0001)
│   │   ├── ops.py           #   operaciones tipadas que proponen versiones (JAJ-68)
│   │   ├── tools.py         #   las tools del agente sobre los proyectos, con límites (JAJ-67)
│   │   ├── mcp.py           #   /mcp: las tools para la CLI de IA del usuario (JAJ-54, JAJ-67)
│   │   └── loop.py          #   el loop del chat del editor con Claude (JAJ-67)
│   ├── catalog/             # catálogo de números con procedencia (copia de spikes/jaj-45-numeros/catalog.json)
│   ├── costs/               # costo mensual por componente (JAJ-72)
│   │   ├── prices.py        #   precios fechados: prices/aws.json y prices/manual.json (copias de JAJ-11)
│   │   ├── estimate.py      #   estimate_cost(modelo) y cost_delta(a, b)
│   │   └── failure.py       #   failure_cost(modelo, run): ventas en juego por hora (JAJ-74)
│   ├── ingest/              # ingesta determinista del repo (ADR 0001, paso 1)
│   │   └── iac.py           #   archivos de despliegue → servicios y números OBSERVADO (JAJ-60)
│   ├── samples/             # modelos de ejemplo que sirve GET /models (salida de JAJ-45)
│   ├── db/                  # modelo de datos (JAJ-55) y ProjectStore sobre Postgres (JAJ-56)
│   └── cli.py               # correr una simulación desde la terminal
└── tests/
    ├── fixtures/            # versión fija del modelo del template (anterior a JAJ-47) para los tests del motor
    ├── engine/              # tests del kernel y del motor
    ├── agent/               # tests de las operaciones, las tools, el MCP y el loop (con un LLM falso)
    ├── costs/               # tests de los precios y del costo (contra el spike de JAJ-11)
    ├── ingest/              # tests del lector de archivos de despliegue
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

La ingesta de repos genera los campos opcionales de caché y colas para los patrones que reconoce. Las llamadas sin un patrón identificado conservan su tiempo de espera.

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

- Si falta `hit_ratio` o su valor es `null`, la caché se simula con 0 % de aciertos y el motor emite un aviso. `--cache-hit` en el CLI, o `cache_hit_ratio` en `simulate()`, reemplaza la tasa de todas las cachés.
- Con una sola cola, el motor la asigna por defecto a los pasos `background` sin `queue`. Un paso con `infer_queue: false` conserva solo el tiempo de encolado si falta una cola explícita, como en las tareas locales de `BackgroundTasks`.
- La request no espera al trabajo. El trabajo espera un worker libre y usa su propia conexión a la DB, no el pool de la API. Sus consultas sí ocupan la CPU de la DB.
- Si la cola está en su `max_length`, encolar falla y la request termina con error `queue_full`. Sin `max_length`, la cola crece sin límite.
- El `Run` trae `cache` (aciertos y fallos) y `queues` (encolados, procesados, rechazados, cola al final y latencia de los trabajos).

La ingesta genera `on_miss` cuando encuentra un `get` de caché, una rama que consulta la DB solo si falla y un `set` o `setex` de la misma clave. Para Celery, el extractor resuelve las funciones de `.delay()` o `.apply_async()` con cola explícita y devuelve sus efectos en `jobs`, un mapa por identificador de función. El generador usa esos efectos para producir `job_steps` cuando la cola tiene un solo perfil de trabajo. Lee la concurrencia de workers dedicados declarados en Compose o Kubernetes.

Los datos que falten quedan como preguntas en `deployment.iac.missing`. Al construir el modelo, `--answers` admite `overrides.cache_hit_ratio` como mapa de `archivo:línea` a fracción y `deployment.queues` como mapa de nombre de cola a `workers` y `max_length`. Un `max_length` explícito de `null` indica una cola sin límite.

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

### Tráfico que cambia en el tiempo (JAJ-71)

Sin perfil, el motor simula una tasa constante: las req/s del escenario, o `rps`. Con `traffic_profile`, la tasa sigue tramos en orden. Cada tramo dura `duration_s` y va linealmente de `from_multiplier` a `to_multiplier` veces la tasa base:

```jsonc
"traffic_profile": [
  {"duration_s": 60,  "from_multiplier": 0.35, "to_multiplier": 1},    // subida
  {"duration_s": 120, "from_multiplier": 1,    "to_multiplier": 1},    // meseta
  {"duration_s": 60,  "from_multiplier": 1,    "to_multiplier": 0.5}   // bajada
]
// o "traffic_profile": "pico": la misma forma escalada a duration_s (25 % de subida, 45 % de meseta, 30 % de bajada)
```

**Qué cambia en el motor:**
- **Duración:** con una lista de tramos, la duración es la suma de los tramos y `duration_s` no se usa. Con `"pico"`, la forma se escala a `duration_s`.
- **Llegadas `poisson`:** se generan a la tasa del pico y cada una se acepta con probabilidad `perfil(t) / pico` (*thinning*, el método estándar para un Poisson con tasa variable).
- **Llegadas `uniform`:** la siguiente llega `1 / tasa(t)` segundos después.

**Qué agrega al `Run`:**
- **`series[].target_rps`:** las req/s que pide el perfil en cada segundo, para dibujar la curva pedida contra lo que se atiende (`ok`). Sin perfil es la tasa constante.
- **`traffic_profile`:** los tramos en req/s, con su segundo de inicio y de fin. Sin perfil es `null`.

**El tope de requests por llamada** (300.000) usa el multiplicador medio del perfil.

**La forma de `"pico"`** es la que usa el editor en sus datos de ejemplo. Es una elección de diseño para mostrar un evento, no una medición: en JAJ-59, el usuario la va a poder dar en el chat.

**Validación** (`tests/engine/test_traffic_profile.py`), con capacidad de 100 req/s:

| Tramo | Duración | Qué pasa con la cola |
| -- | -- | -- |
| 50 req/s | 30 s | casi no hay |
| 150 req/s | 30 s | crece a ~1.500 requests, como sale de la cuenta (50/s × 30 s) |
| 30 req/s | 60 s | se vacía |

Además:
- **Un perfil plano en 1×** da exactamente el mismo `Run` que la tasa constante.
- **Con Poisson,** el total de llegadas es tasa × duración × multiplicador medio (±5 %).

**Por qué importa la duración:** el timeout del cliente es de 30 s, así que una simulación de 30 s no alcanza a mostrar los errores por timeout de un evento largo. Con el template en CyberDay y `"pico"` en 300 s:
- **La v2 (API ×3 y pooler)** aguanta la subida, pero a los 2 minutos se satura la DB y los errores llegan al 60 %.
- **La v1 llega al 81 %** de errores.

### Cuando el sistema no alcanza a atender (JAJ-89)

`error_rate` solo cuenta las requests que terminaron, sea bien o con error. Una request que sigue en fila cuando se acaba la simulación, y todavía no llega al timeout del cliente, no es ni ok ni error: queda en `in_flight`. En un sistema saturado la fila crece sin parar, así que un "0 % de errores" puede esconder un colapso. Con branchpoint-shop-demo a 400 req/s, 60 s y semilla 7 (el perfil de su `simulate_demo.py`), el `Run` daba 0 % de errores con un p95 de 22 s.

Por eso el `Run` trae `saturation`:
- `saturated`: se cumplen dos condiciones.
  1. **Muchas requests sin respuesta:** al menos 5 % (`UNANSWERED_SATURATED`).
  2. **Una espera que crece o que llegó al timeout:** la espera que implica la fila (Ley de Little: fila / tasa de llegada) es al final al menos 1,5 veces la de la mitad, más 0,25 s (`WAIT_GROWTH` y `WAIT_GROWTH_MIN_S`). También cuenta si llegó al 80 % del timeout del cliente (`TIMEOUT_SHARE`) **y ya hay timeouts**: un endpoint sano que tarda 25 s deja una espera de 25 s, pero sus requests no vencen. En simulaciones de más de ~2× el timeout, la espera deja de crecer porque las requests que vencen pasan a error, pero el sistema sigue colapsado.

  La primera condición sola no basta. Sin saturación, la fracción en curso es latencia / duración: un endpoint sano de 3 s (una llamada a un LLM) deja 10 % en curso en 30 s. Pero en un sistema sano la espera se estabiliza en la latencia, y en uno saturado crece sin parar. La tasa de llegada se mide en una ventana de 3 s, así que un perfil que sube no se confunde con una fila que crece. Con menos de 4 s simulados no se evalúa.
- `wait_mid_s` y `wait_end_s`: la espera a la mitad y al final.
- `label` (`SUPUESTO`) y `source`: la procedencia de `saturated`, armada desde las constantes del motor. El editor puede mostrarla junto al aviso. El agente la recibe de dos formas:
  - en `simulate` y `compare`, dentro del bloque `saturation`, con `label` y `source` (son de `saturated`; los conteos salen del motor);
  - en las metas (`goals.errors` y `goals.p95`), anidada en `saturated_provenance`, para que no pise el `label` y el `source` del piso del 1 %.
- `unanswered` y `unanswered_rate`: cuántas quedaron sin respuesta.
- `error_rate_if_unanswered_fail`: la tasa de error si esas requests terminaran fallando. Es el techo de `error_rate`.
- `offered_rps`: las req/s que llegaron (con perfil, el promedio).
- `message`: el aviso en español. También va primero en `warnings`, y dice cuánto crece la espera y dónde estaba la fila.

Los umbrales (5 %, ×1,5, 0,25 s y 80 % del timeout) y la forma de medir (ventana de 3 s, mínimo de 4 s) son **SUPUESTO**: los eligió el equipo, con el razonamiento de arriba, y no salen de una medición. Los tests cubren los dos lados: el colapso con 0 % de errores se marca, también en simulaciones de 60 y 120 s; un endpoint lento, una simulación corta o un perfil que sube no se marcan (`tests/engine/test_saturation.py`). Con branchpoint-shop-demo (60 s, semilla 7), a 400 req/s queda 39 % sin respuesta y la espera crece de 11 a 22 s. A 100 req/s no aparece el aviso.

En `compare`, `summary` agrega "Ojo: v1 no alcanza a atender este tráfico (v1 deja 39 % de las requests sin respuesta al terminar): su tasa de error es un piso". Las metas del agente (`simulate` y `compare` de `app/agent/tools.py`) usan ese techo, así que una versión saturada nunca "cumple" por su 0 % de errores. El bloque `errors` dice con qué tasa juzgó (`basis`, `value` y el `error_rate` original), y el de `p95` dice por qué no cumple.

**Runs guardados (JAJ-75):** no hay que subir ninguna versión. `ENGINE_VERSION` es el hash del código de `app/engine` y `app/models`, así que este cambio ya cambia la clave de los runs guardados y se vuelven a simular. Un `Run` guardado antes, sin `saturation`, se sigue leyendo (queda en `None`).

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

# CyberDay con subida, meseta y bajada en 5 minutos (la serie por segundo trae target_rps)
python -m app.cli app/samples/full-stack-fastapi-template.model.json --scenario cyberday --profile pico --duration 300 --out run.json

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
| `POST` | `/projects/{id}/versions/{n}/runs` | Simula la versión `n`. Body: el de `POST /runs` sin `model`. Si ya se simuló con los mismos parámetros, devuelve el run guardado (ver "Runs guardados" abajo). |
| `POST` | `/projects/{id}/versions/{n}/ops` | Aplica `{"ops": [...], "note"}` a la versión `n` y guarda el resultado como versión nueva (`origin: agente`, antecesora `n`). Devuelve la versión con `changes` (una línea por operación) y `warnings`. Ver "Operaciones" abajo. |
| `POST` | `/projects/{id}/compare` | Simula las versiones `a` y `b` con el mismo escenario y semilla. Devuelve los dos `Run` y `delta`: p50/p95/p99, errores y throughput (`a`, `b`, `diff`, `pct`), si cambió el cuello de botella y `model_changes` (qué valores cambiaron entre los modelos). También trae `cost_a`, `cost_b` y `cost_delta` (US$/mes total y por componente), `failure_a` y `failure_b` (ventas en juego por hora, JAJ-74) y `summary`, la comparación en una frase. `region` opcional para los costos. |
| `GET` | `/projects/{id}/scenarios` | Los escenarios del proyecto (`name`, `multiplier` o `rps`, `description`). Ver "Escenarios del proyecto" abajo. |
| `GET` | `/projects/{id}/scenarios/{name}` | Un escenario. 404 si el proyecto no lo tiene. |
| `PUT` | `/projects/{id}/scenarios/{name}` | Crea o reemplaza el escenario. Body: `{"multiplier": 20}` (× el pico de cada versión) o `{"rps": 300}` (req/s fijas), y `description` opcional. |
| `GET` | `/projects/{id}/versions/{n}/costs` | Costo mensual de la versión `n`, por componente. `?region=us-east-1` (por defecto) o `sa-east-1`. |
| `POST` | `/costs` | Costo mensual de `{"model", "region"}`, por componente. Ver "Costos" abajo. |

**Dónde se guardan los proyectos:** con `DATABASE_URL` (en `backend/.env`), en Postgres (`app/db/postgres_store.py`). Sin ella, en memoria, y se pierden al reiniciar la API. Las dos implementan `ProjectStore` (`app/api/store.py`), así que las rutas son las mismas. Con Postgres, los ids de proyecto son `uuid`.

**Login y proyectos por usuario (JAJ-78):** con `SUPABASE_URL` en el entorno, todas las rutas de `/projects` piden el token de sesión de Supabase Auth: `Authorization: Bearer <access_token>`, el que entrega `supabase.auth.getSession()` en el frontend.
- **Cómo se valida** (`app/api/auth.py`): la firma se revisa con las claves públicas del proyecto (JWKS, en `{SUPABASE_URL}/auth/v1/.well-known/jwks.json`), que se bajan una vez y se vuelven a bajar si aparece una clave nueva. También se revisan `exp`, `aud = authenticated` e `iss = {SUPABASE_URL}/auth/v1`. Para un proyecto que todavía firma con el secreto compartido (HS256), va `SUPABASE_JWT_SECRET`.
- **Errores:** sin token, o con uno vencido o inválido, 401 `unauthorized`, con el motivo en español. Si no se pueden bajar las claves, 503 `auth_unavailable`.
- **Cada usuario ve solo lo suyo.** El proyecto guarda `owner_id`, que es el `sub` del token (el id de `auth.users`). El de otro usuario responde 404, como si no existiera: no se puede listar, abrir, simular, comparar, costear ni escribirle versiones u operaciones. Los runs guardados y los escenarios cuelgan del proyecto, así que quedan aislados con él. Todas las rutas de proyectos sacan el store de `get_store`, que exige la sesión y filtra por dueño, así que una ruta nueva no puede saltarse el filtro.
- **Proyectos anónimos de antes de JAJ-78:** no son de nadie, y con login no se ven.
- **Sin login** siguen `GET /health`, `GET /models`, `POST /graph`, `POST /runs` y `POST /costs`, que no guardan nada. Con ellas se puede ver el catálogo de templates sin cuenta.
- **`BRANCHPOINT_AUTH=off`** (o no tener `SUPABASE_URL`) apaga el login: los proyectos quedan sin dueño, como antes. Sirve para usar el editor en local mientras no tenga login (JAJ-77). En producción no se pone.
- **Postgres:** el backend entra con el rol `postgres`, que se salta RLS, así que el aislamiento lo hace `PostgresProjectStore`, filtrando por `owner_id`.

**Escenarios del proyecto (JAJ-76):** los escenarios son del proyecto, no de una versión. Así se compara cualquier par de versiones con el mismo escenario.
- **Al crear el proyecto** se cargan los de `traffic.scenarios` de la v1 (`pico_normal` ×1 y `cyberday` ×20), con su multiplicador.
- **`multiplier`** se multiplica por el pico del modelo de cada versión (`traffic.peak_rps`). CyberDay ×20 da 262,4 req/s en el template y 100 req/s en una v2 con pico 5. **`rps`** son req/s fijas, iguales en todas las versiones.
- **`POST /projects/{id}/versions/{n}/runs` y `compare`** buscan el escenario por nombre en el proyecto, no en el modelo. Uno creado con `PUT` sirve para cualquier versión, aunque no esté en su `traffic.scenarios`. Si no existe, responden 422 `unknown_scenario` con `available`. Con `rps` en la request, el escenario es solo un nombre y no se busca.
- **Al editar un escenario** cambia la tasa final y, con ella, la clave del run guardado: se vuelve a simular y nunca se devuelve un run con la tasa vieja.
- **Duración, llegadas y timeout** siguen saliendo de la request. Las columnas de la tabla para eso (`duration_s`, `arrivals`…) todavía no se usan.

**Runs guardados (JAJ-75):** `POST /projects/{id}/versions/{n}/runs` y `compare` guardan cada `Run` y, si se pide lo mismo otra vez, devuelven el guardado sin simular. Funciona así porque las versiones no se editan y el motor es determinista con la misma semilla.
- **La clave** (`cache_key`, en `app/api/run_cache.py`) es el sha256 del proyecto, el número de versión, los `RunParams` (escenario, semilla, duración, tasa, perfil, créditos de CPU…) y `ENGINE_VERSION`. La tasa es la final: si viene de un escenario del proyecto, ya va calculada con el pico de la versión (JAJ-76).
- **`ENGINE_VERSION`** es el hash del código de `app/engine` y `app/models`. Si cambia el motor, cambia la clave y los runs viejos dejan de usarse, sin subir ningún número a mano.
- **El header `X-Branchpoint-Run-Cache`** dice `hit` si el run venía guardado y `miss` si se simuló. En `compare` van los dos, de `a` y de `b` (`hit,miss`). El CORS lo expone, así que el editor lo puede leer.
- **Dónde quedan:** con Postgres, en la tabla `runs`, con el `Run` completo en `result` y sus métricas en columnas (`p95_ms`, `error_rate`, `throughput_rps`, `bottleneck_resource`), y sobreviven a un reinicio. En memoria, se pierden con el resto.
- **Qué no se guarda:** una simulación que falla (422) y `POST /runs`, que no tiene versión. La comparación tampoco: es la diferencia entre dos runs guardados, y se recalcula.

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
  "cpu_credits": "sustained",   // DB con créditos de CPU (db.t4g.*): "sustained" (vCPU sostenidos) o "burst" (todos)
  "traffic_profile": null       // "pico" o una lista de tramos: tasa que cambia en el tiempo (JAJ-71)
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

### Agente: tools, MCP y chat (JAJ-67)

El agente es un loop de tool use (ADR 0001): el LLM pide tools y el backend las ejecuta. Las tools están una sola vez, en `app/agent/tools.py`, y se exponen de dos formas (JAJ-54):

1. **MCP en `/mcp` (modo principal).** El loop corre en la CLI de IA del usuario, por ejemplo Claude Code con su suscripción, y el backend solo ejecuta las tools. Branchpoint no ve ninguna credencial de IA.

   ```bash
   claude mcp add --transport http branchpoint http://localhost:8000/mcp --header "Authorization: Bearer <token de sesión de Supabase>"
   ```

   - **Con login:** el token es el mismo que usa el editor (JAJ-78), y cada usuario ve solo sus proyectos. Sin token, `/mcp` responde 401. El token de larga duración para emparejar la CLI llega con JAJ-81.
   - **Sin login** (`BRANCHPOINT_AUTH=off`): no hace falta el header.

2. **Chat del editor: `POST /projects/{id}/chat` (modo secundario).** El loop corre en el backend con Claude (`claude-opus-5-5`), con un máximo de 8 vueltas por mensaje. Transmite NDJSON, una línea por evento: `text`, `tool_call`, `tool_result`, `done` (con `usage` y `cost` de la tabla de precios) y `error`.
   - **Credencial del usuario:** su API key en el header `X-Anthropic-Api-Key`. Se usa en esa request y no se guarda.
   - **Modo demo:** con `BRANCHPOINT_CHAT_DEMO=on` y sin header, se usa la credencial del equipo (el SDK la resuelve del entorno), con 30 mensajes por usuario y por día.
   - **Sin ninguna de las dos:** responde 422.

| Tool | Qué hace |
| -- | -- |
| `list_projects` | Los proyectos del usuario y sus versiones |
| `get_model`, `list_assumptions` | Resumen de una versión (despliegue, tráfico, endpoints con `archivo:línea`, metas) y sus `SUPUESTO` |
| `list_scenarios` | Los escenarios del proyecto |
| `simulate` | Simula una versión con un escenario del proyecto: p95, errores, cuello de botella con su línea, procedencia y si cumple las metas |
| `compare` | Dos versiones con el mismo escenario y semilla: delta de p95, errores y costo, ventas en juego y metas |
| `estimate_cost`, `ops_schema` | Costo mensual por componente; schema de las operaciones |
| `propose_version` | Aplica operaciones (JAJ-68) y guarda una versión con origen `agente`. No simula: después va `compare` |
| `set_traffic` | Tráfico del usuario → pico en req/s y escenario del evento, como versión nueva |
| `set_deployment` | Réplicas, vCPU o plan de DB del usuario, como versión nueva |
| `set_goals` | Metas del proyecto: p95, errores y presupuesto |

Reglas, iguales en los dos modos:

- **Ningún número libre del LLM.** `set_traffic`, `set_deployment` y `set_goals` piden `quote`, la frase textual del usuario, y cada número tiene que aparecer en ella (se aceptan 100.000, 100k, 1 % = 0,01, 300 ms = 0,3 s). `simulate` y `compare` no reciben req/s ni duración: la tasa sale del escenario, y la duración la fija el servidor (60 s, o menos si la tasa no cabe en el tope de requests por llamada).
- **Procedencia en cada resultado** (`label`, fuente con escenario, semilla, req/s y segundos simulados) y todas las advertencias del motor.
- **Errores con la forma `{"error": "..."}`,** también para argumentos desconocidos o mal tipados. En MCP, un middleware los rechaza antes de la tool, porque el SDK los descarta en silencio.
- **Límites por usuario:** 60 llamadas por minuto y 300 simulaciones por día (`compare` cuenta 2). Son en memoria, por instancia de la API.
- **Metas:** `projects.slo_p95_ms`, `slo_error_rate` y `budget_usd_month` del modelo de datos (JAJ-55). El p95 solo mide las requests exitosas. Por eso, si el usuario no declaró una meta de errores, `simulate` y `compare` exigen un piso de 1 % (`SUPUESTO`, y lo dicen): una versión que rechaza el 85 % de las requests nunca cumple, aunque su p95 sea bajo.

`read_file` y `grep` no están. En el modo MCP sobran, porque la CLI del usuario lee su repo local. Para el chat haría falta guardar el repo extraído.

`BRANCHPOINT_MCP_ALLOWED_HOSTS` (separados por coma; por defecto localhost) define los `Host` que acepta `/mcp`, como protección contra DNS rebinding. En producción va el dominio de la API.

### Costos (JAJ-72)

`estimate_cost(modelo, region)` (`app/costs/estimate.py`) devuelve el costo mensual de una arquitectura, por componente. Las fórmulas son las del spike de JAJ-11 (`spikes/jaj-11-costos/costs.py`) y los precios son sus snapshots fechados (`app/costs/prices/`). La diferencia es que se aplican a lo que dice el modelo, no a un escenario genérico:

| Componente | Fórmula | Cuándo aparece |
| -- | -- | -- |
| API (Fargate ARM) | réplicas × (vCPU × US$/vCPU-h + GB × US$/GB-h) × 730 h | `deployment.api.provider` es `fargate` |
| DB Supabase | 25 + max(0, compute − 10) + disco y egreso sobre lo incluido (1 MB de DB y 4 MB de egreso por usuario) | `deployment.db.provider` es `supabase` |
| DB RDS PostgreSQL | US$/h × 730 + max(20 GB, 1 MB por usuario) × US$/GB-mes de gp3 | `deployment.db.provider` es `rds_postgres` |
| Balanceador (ALB) | (US$/h + LCU × US$/LCU-h) × 730; LCU según conexiones nuevas y GB | la API está en Fargate |
| Transferencia de la API | respuestas de 50 KB, sobre los 100 GB gratis del mes, por tramos | el modelo trae usuarios mensuales y perfil de uso |
| Caché (Valkey serverless) | (1 GB + 1 KB por usuario) × US$/GB-h × 730 + operaciones × US$/ECPU | algún endpoint tiene un paso de caché |

**Qué trae cada línea:**
- **El costo con procedencia** (`label`, `source` y `date`). La fuente lleva el SKU y la URL del archivo de AWS, o la página del proveedor con su fecha de lectura.
- **La fórmula** que se usó.
- **Los números** que entraron en la fórmula (`inputs`).
- **El nodo del grafo** al que corresponde (`node`), para el `CostBreakdown` del editor.

**Etiqueta:** es la más débil entre el precio (`ESTIMADO`, precio de lista) y los datos del modelo. Como el template tiene usuarios y réplicas `SUPUESTO`, su costo también queda `SUPUESTO`.

**Lo que no tiene precio** queda en `unpriced`, con el motivo:
- los workers de las colas, porque el modelo no dice en qué máquina corren;
- un plan que no está en los precios;
- el tráfico, si el modelo no trae usuarios mensuales.

Los estáticos del frontend (CDN y S3) no se incluyen, porque el modelo describe la API.

**El template coincide con el spike** (`tests/costs/test_estimate.py` importa su `costs.py` y compara componente por componente):

| Componente | US$/mes | Spike |
| -- | --: | -- |
| API: 1 × (1 vCPU, 2 GB) | 28,84 | igual |
| DB: Supabase Micro, 100.000 MAU | 48,86 | igual (`supabase_mes`) |
| ALB | 21,61 | igual |
| Transferencia: 13,6 M de requests, 648 GB | 49,36 | 58,36 (ver abajo) |
| **Total** | **148,67** | |

La única diferencia es buscada. `por_tramos` del spike cobra la transferencia desde el primer GB, pero AWS regala los primeros 100 GB del mes (*"first 10 TB / month data transfer out beyond the global free tier"*). Aquí el primer tramo pagado empieza después de esos 100 GB: son US$9 menos.

Los precios son copias de `spikes/jaj-11-costos/prices`, y `tests/costs/test_prices.py` falla si se separan. Para actualizarlos, hay que correr `extract_aws_prices.py` en el spike y copiar los archivos.

```bash
# costo de la v1 y de una v2 con 3 réplicas, y la diferencia en compare
curl -s localhost:8000/projects/$P/versions/1/costs
curl -s -H "Content-Type: application/json" -d '{"ops": [{"op": "scale_api", "replicas": 3}]}' localhost:8000/projects/$P/versions/1/ops
curl -s -H "Content-Type: application/json" -d '{"a": 1, "b": 2, "duration_s": 10}' localhost:8000/projects/$P/compare | python -c 'import json,sys; print(json.load(sys.stdin)["cost_delta"])'
```

**API o DB sin precio (JAJ-88).** Solo hay precios para la API en `fargate` y para la DB en `supabase` o `rds_postgres`. En `local` cuestan US$0, y en otro proveedor (por ejemplo `render`) no tienen precio. En ambos casos el total no las incluye, así que **no cambia con sus réplicas ni con su plan**. Un repo importado con Docker Compose queda en `local`. Con branchpoint-shop-demo, por ejemplo, 1 y 5 réplicas daban "= Igual", y los US$62/mes eran solo la caché.
- **`CostEstimate.missing`:** `["api", "db"]`, los componentes sin precio. El primer elemento de `warnings` lo explica y dice qué proveedor usar para comparar.
- **`CostDelta.missing`:** los que faltan en alguna de las dos versiones. `missing_a` y `missing_b` dicen en cuál. `a`, `b`, `diff`, `pct` y `by_line` **cuentan solo los componentes con precio en las dos**. Si v1 está en local y v2 en Fargate, sumar la API (y su ALB) haría que todo el "+US$X" fuera la API de v2, presentado como una diferencia. En ese caso el resumen dice "sin contar la API (con precio solo en v2)". Los totales completos siguen en `cost_a` y `cost_b`.
- **Proveedores con precio:** lo que falta se detecta de las mismas funciones que calculan el precio. `PRICED_API` y `PRICED_DB` solo arman el aviso, y un test comprueba que coinciden.
- **En `compare`,** `summary` lo dice: "v2 cuesta +US$0.00/mes respecto de v1 sin contar la API ni la DB, que no tienen precio (despliegue local o proveedor sin precios)".
- **El agente** recibe `delta.usd_month_missing` en `compare`. Con componentes sin precio, la meta de presupuesto queda en `"ok": null` con su motivo (`basis`), y `meets_all` en `null` si nada más falla. Así no dice que "cumple el presupuesto" contando, por ejemplo, solo la caché.

### Costo de fallar (JAJ-74)

`failure_cost(modelo, run)` (`app/costs/failure.py`) da las ventas en juego por hora según lo que simuló el motor. Es la fórmula de JAJ-11: sesiones por hora × fracción que falla × conversión × ticket. La conversión y el ticket salen del `business` del modelo, y las requests por sesión de `traffic`. La cota de `build_model.py` (`checks.sales_at_stake_per_hour`) suponía que todo falla; aquí la fracción sale de la tasa de error del `Run`.

**Es un rango, no un número.** Una sesión hace varias requests (17 en el perfil medio), y no se sabe si con una request fallida se pierde la venta:

| Cota | Fracción de sesiones que se pierden | Supone |
| -- | -- | -- |
| Piso | `e`, la tasa de error | solo se pierde la venta de la request que falló |
| Techo | `1 − (1 − e)^k`, con `k` requests por sesión | se pierde si falla *cualquier* request de la sesión, con fallas independientes |

**Qué trae:**
- **Cada monto** con su procedencia. La etiqueta es la más débil de sus datos: con conversión y ticket `SUPUESTO`, el monto también es `SUPUESTO`.
- **"Si fallara todo"** (`at_stake_per_hour`), que calza con la cota de `build_model.py`.
- **`is_floor`:** algún recurso pasa el 90 %, así que el motor es optimista (JAJ-44) y el monto es "al menos".
- **`too_short`:** el sistema está saturado, pero todavía no hay errores. El timeout del cliente es de 30 s, así que en una simulación de 30 s no alcanza a vencer ninguno (JAJ-71). En vez de decir que no hay ventas en juego, el mensaje pide simular más tiempo.

**En `compare`,** `summary` lo junta con el costo de infraestructura. Con el template en CyberDay (120 s) y la v2 con API ×3 y pooler:

> v2 cuesta +US$57,66/mes respecto de v1 y evita entre US$1 y US$9.598 por hora en ventas en juego (al menos).

El rango es amplio porque las dos versiones fallan mucho: la v1 con 75 % de errores y la v2 con 46 %. Con esas tasas, el techo de las dos se acerca a "si fallara todo". La diferencia de los pisos es lo que la v2 evita con seguridad.

Los tests están en `tests/costs/test_failure.py` y `tests/api/test_costs.py`:
- la versión con más errores muestra más ventas en juego;
- la fórmula sale del `Run`;
- "si fallara todo" calza con `build_model` (±0,2 % con llegadas uniformes);
- las etiquetas y el piso;
- la simulación demasiado corta;
- sin errores no hay pérdida.

Desde Python:

```python
from app.models import load_model
from app.engine import simulate

run = simulate(load_model("modelo.json"), "cyberday", seed=0, duration_s=60)
print(run.bottleneck.message)
run.to_dict()  # listo para JSON
```
