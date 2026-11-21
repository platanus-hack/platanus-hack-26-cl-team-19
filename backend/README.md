# Backend de Branchpoint

Por ahora contiene el **motor de simulación** (JAJ-14). La API y la persistencia van a ir en las carpetas que ya están reservadas.

## Estructura

```
backend/
├── pyproject.toml           # dependencias (el motor solo usa la librería estándar) y pytest
├── app/
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
    └── engine/              # tests del kernel y del motor
```

El flujo es: **modelo v1 (JSON)** → `load_model()` → `simulate()` → **Run**.

## Cómo modela el sistema el motor

Los recursos se arman desde el `deployment` del modelo:

| Recurso | Capacidad | Qué lo ocupa |
| -- | -- | -- |
| CPU de la API (`api_cpu`) | `min(workers, vCPU) × réplicas` núcleos | CPU base de cada request y pasos de CPU (ej. hash de contraseña) |
| Hilos de la API (`api_threads`) | hilos por worker × workers × réplicas | endpoints `def` (síncronos), durante toda la request |
| Pool de conexiones (`db_pool`) | pool por worker × workers × réplicas (tope: conexiones de la DB) | desde la primera consulta hasta el final de la request |
| CPU de la DB (`db_cpu`) | vCPU de la DB | cada consulta, durante su tiempo |

- Cada request recorre los `steps` de su endpoint en orden. Respeta `repeat` (N+1).
- Esperar una conexión más que el timeout del pool es un error (`pool_timeout`).
- Tardar más que el timeout del cliente (30 s por defecto) también es un error (`client_timeout`). Aun así, el servidor hace el trabajo, como se vio en JAJ-9.
- Con vCPU fraccionarios, por ejemplo 0,5 en Supabase Micro, se simula 1 núcleo que tarda el doble.

**Validación:** el modelo se validó contra un sistema real en JAJ-9, JAJ-43, JAJ-42 y JAJ-44. Acierta la saturación con 0–11 % de error. Cerca o sobre la capacidad es optimista, así que el `Run` lo advierte cuando un recurso pasa el 90 %.

## Cómo usarlo

No hace falta instalar Python: todo corre en Docker.

```bash
# tests
docker run --rm -v "$PWD:/w" -w /w python:3.14-slim sh -c "pip install -q pytest && python -m pytest -q"

# simular CyberDay ×20 con el modelo de ejemplo (guarda el Run completo con --out)
docker run --rm -v "$PWD:/w" -w /w python:3.14-slim \
  python -m app.cli tests/fixtures/full-stack-fastapi-template.model.json --scenario cyberday --out run.json
```

En Windows con Git Bash, antepongan `MSYS_NO_PATHCONV=1` y usen `$(pwd -W)` en vez de `$PWD`.

Desde Python:

```python
from app.models import load_model
from app.engine import simulate

run = simulate(load_model("modelo.json"), "cyberday", seed=0, duration_s=60)
print(run.bottleneck.message)
run.to_dict()  # listo para JSON
```
