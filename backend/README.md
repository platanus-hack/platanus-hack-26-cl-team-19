# Backend de Branchpoint

Contiene el **motor de simulación** (JAJ-14) y la **API** que lo expone al editor (JAJ-49). La persistencia va a ir en `app/db`, que ya está reservada.

## Estructura

```
backend/
├── pyproject.toml           # dependencias (FastAPI y uvicorn para la API; el motor solo usa la librería estándar)
├── app/
│   ├── api/                 # API HTTP (FastAPI)
│   │   ├── main.py          #   arma la app: CORS, errores y rutas
│   │   ├── schemas.py       #   lo que recibe POST /runs (RunRequest)
│   │   ├── errors.py        #   formato de los errores ({"error": {"code", "message"}})
│   │   └── routes/          #   una ruta por archivo: health.py, runs.py
│   ├── models/              # estructuras de datos
│   │   ├── architecture.py  #   entrada: el modelo branchpoint.model/v1 (JAJ-45) y load_model()
│   │   └── run.py           #   salida: el Run (branchpoint.run/v1)
│   ├── engine/              # motor de eventos discretos
│   │   ├── kernel.py        #   reloj, cola de eventos y recursos (genérico)
│   │   ├── simulate.py      #   arma los recursos desde el modelo y recorre los pasos de cada request
│   │   └── metrics.py       #   percentiles y series por segundo
│   ├── db/                  # persistencia: vacía por ahora (JAJ-17), ver su README
│   └── cli.py               # correr una simulación desde la terminal
└── tests/
    ├── fixtures/            # modelos de ejemplo (full-stack-fastapi-template, generado por JAJ-45)
    ├── engine/              # tests del kernel y del motor
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

**Validación:** el modelo se validó contra un sistema real en JAJ-9, JAJ-43, JAJ-42 y JAJ-44. Acierta la saturación con 0–11 % de error. Cerca o sobre la capacidad es optimista, así que el `Run` lo advierte cuando un recurso pasa el 90 %. La caché reproduce la prueba de JAJ-44: con 50 % de aciertos, el p95 queda entre −8 % y +6 % de lo medido hasta el 89 % de uso del pool. Al 99 % el motor da el doble (es pesimista ahí) (`tests/engine/test_cache_queue.py`).

## Cómo usarlo

Con Python 3.12 o más nuevo (en Linux, macOS o WSL), desde `backend/`:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# tests
python -m pytest -q

# simular CyberDay ×20 con el modelo de ejemplo (guarda el Run completo con --out)
python -m app.cli tests/fixtures/full-stack-fastapi-template.model.json --scenario cyberday --out run.json

# levantar la API en http://localhost:8000 (documentación interactiva en /docs)
uvicorn app.api.main:app --reload
```

Sin instalar Python, con Docker (en Git Bash de Windows, antepongan `MSYS_NO_PATHCONV=1` y usen `$(pwd -W)` en vez de `$PWD`):

```bash
docker run --rm -v "$PWD:/w" -w /w python:3.14-slim sh -c 'pip install -q -e ".[dev]" && python -m pytest -q'
```

### API

| Método | Ruta | Qué hace |
| -- | -- | -- |
| `GET` | `/health` | Revisa que la API está arriba. |
| `POST` | `/runs` | Simula un modelo y devuelve el `Run` (`branchpoint.run/v1`). No guarda nada (eso es JAJ-17). |

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
  "cache_hit_ratio": null       // reemplaza la tasa de aciertos de las cachés con on_miss
}
```

```bash
# ejemplo: armar el body con el modelo de ejemplo y simular CyberDay
python -c 'import json; m = json.load(open("tests/fixtures/full-stack-fastapi-template.model.json")); print(json.dumps({"model": m, "scenario": "cyberday"}))' > req.json
curl -s -H "Content-Type: application/json" --data @req.json localhost:8000/runs
```

Los errores responden 422 con `{"error": {"code", "message", ...}}`. El `message` está en español y está pensado para mostrarlo tal cual:

| `code` | Cuándo |
| -- | -- |
| `invalid_model` | El modelo no es `branchpoint.model/v1` o le falta un campo. |
| `unknown_scenario` | El escenario no está en el modelo. Trae `available` con los que hay. |
| `invalid_parameters` | Un parámetro está fuera de rango, falta o sobra. Trae `fields` con cada campo. |
| `run_too_large` | Tasa × duración pasa las 300.000 requests (unos pocos segundos de cálculo). |

- **CORS:** por defecto acepta llamadas desde el Nuxt de desarrollo (`http://localhost:3000`). Para otros orígenes, usen `BRANCHPOINT_CORS_ORIGINS`, separados por coma.
- **La simulación ocupa CPU:** por eso la ruta es `def` y no `async def`. FastAPI la corre en su pool de hilos y no bloquea las demás requests mientras simula.

Desde Python:

```python
from app.models import load_model
from app.engine import simulate

run = simulate(load_model("modelo.json"), "cyberday", seed=0, duration_s=60)
print(run.bottleneck.message)
run.to_dict()  # listo para JSON
```
