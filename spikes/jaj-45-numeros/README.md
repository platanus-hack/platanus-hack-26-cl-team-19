# JAJ-45: de dónde salen los números del modelo y cómo se cruzan con el grafo

Issue: [JAJ-45](https://linear.app/jajathom/issue/JAJ-45/definir-como-la-app-obtiene-los-numeros-del-modelo-y-los-cruza-con-el)

## Resultado en 5 líneas

1. **Decisión:** el modelo v1 se arma con tres fuentes.
   * El repo: la topología de JAJ-7, más la forma de cada query, los workers y el pool.
   * Un catálogo fijo de números: los tiempos de JAJ-8 y los precios de JAJ-11.
   * Las 3 respuestas del usuario: tráfico, despliegue y negocio.
2. **El repo da más números de lo esperado.**
   * La forma de cada query (lectura por PK, búsqueda, rango, `COUNT`, escaneo, commit) le asigna su tiempo de JAJ-8 sin preguntar nada.
   * Los workers y el pool se leen como `OBSERVADO`, incluso cuando vienen de `settings.X` o de `config("X", default=…)`.
3. **Cada número del modelo trae `value`, `unit`, `label`, `source` y `date`.** Un número calculado hereda la etiqueta más débil de sus entradas. Los `SUPUESTO` quedan en una lista aparte para que la UI los resalte.
4. **En el template de FastAPI el modelo ya encuentra algo:**
   * Corre con 4 workers de 15 conexiones cada uno: 60 conexiones, justo el límite de Supabase Micro.
   * En CyberDay ×20 (262 req/s), con capacidad de nube, la CPU de la API queda al 493 %, sobre todo por el hash de contraseñas, y la de la DB al 175 % (JAJ-47).
5. **Lo más débil son tres números:**
   * El tamaño de las tablas, que define el costo de los escaneos.
   * La vCPU de los planes compartidos de Supabase y su procesador (se asume Graviton2).
   * El factor laptop → nube: `ESTIMADO` con ±30 %, por un solo resultado público de Graviton3 (JAJ-46).

   Están marcados como `SUPUESTO` y son los primeros que hay que calibrar o pedir.

## Cómo correrlo

```bash
python3 build_model.py <ruta-al-repo> --answers answers/full-stack-fastapi-template.json -o modelo.json
```

Requiere solo Python 3.12 (stdlib) y usa el extractor de `spikes/jaj-7-ingestion/`. Igual que el extractor, no importa ni ejecuta el código analizado. Es determinista: dos corridas con el mismo repo y las mismas respuestas dan el mismo archivo, salvo la fecha.

## A. Números que salen del repo (`OBSERVADO`)

| Parámetro | Dónde se lee | Si no está |
|---|---|---|
| Workers del servidor | `--workers N` o `-w N` en Dockerfile, compose, Procfile o scripts; `workers = N` en la configuración de gunicorn | 1 (`ESTIMADO`, default de uvicorn y `fastapi run`) |
| `pool_size`, `max_overflow`, `pool_timeout` | Argumentos de `create_engine` / `create_async_engine`, también desde un dict `**kwargs` | Defaults de SQLAlchemy: 5 + 10, con 30 s de espera (`ESTIMADO`, JAJ-8) |
| Tamaño del pool de asyncpg | `max_size` de `asyncpg.create_pool` | 10, sin overflow (`ESTIMADO`) |
| Valores que vienen de la configuración | `settings.X` → `x: int = 10`; `config.X` → `config("X", default=20)` | Se marcan `OBSERVADO`, con la nota de que se pueden cambiar por variable de entorno |
| Endpoint `def` o `async def` | El AST del handler | No aplica |
| Timeouts de llamadas HTTP | Ya lo marcaba JAJ-7 (`[sin timeout]`) | No aplica |

Ejemplos de lo que encuentra:

* **Template:** `4 workers en backend/Dockerfile:65` y `create_engine` sin `pool_size`.
* **realworld:** `max_size` de asyncpg = 10, leído de `app/core/settings/app.py:22`.
* **Dispatch:** pool de 20 + 10 con 30 s de espera, leído de los defaults de `src/dispatch/config.py`.

## B. Cruce grafo → parámetros

El extractor de JAJ-7 ahora le pone a cada acceso a DB una forma (`shape`). La forma se deduce de la cadena del statement (`select(...).where(...).limit(...)`, `db.query(M).filter(...).first()`) y, en aiosql, del SQL y del sufijo `^`/`$` del nombre. Cada forma toma su número de `catalog.json`:

| Forma | Ejemplo en el código | Parámetro de JAJ-8 | Etiqueta |
|---|---|---|---|
| `pk` | `session.get(User, id)`, `session.refresh(obj)` | lectura por PK: 0,10 ms | `CALIBRADO` |
| `lookup` | `select(User).where(User.email == x)` + `.first()` | lectura por PK: 0,10 ms | `ESTIMADO`: supone índice en el filtro |
| `range` | `.where(...).offset().limit()`, `.all()` con filtro | rango por índice de 50 filas: 0,14 ms | `ESTIMADO`: supone índice y unas 50 filas |
| `count` | `select(func.count()).where(...)` | rango por índice: 0,14 ms | `ESTIMADO` |
| `count_all`, `scan` | `select(func.count()).select_from(Item)` sin filtro; `SELECT tag FROM tags` | 50 ms por millón de filas × filas de la tabla | `CALIBRADO` × filas `SUPUESTO` (100.000 por defecto) |
| `commit` | `session.commit()`, `INSERT` en aiosql | escritura con commit: 1,1 ms | `CALIBRADO` |
| `stage` | `session.add`, `session.delete` | 0 ms: el SQL sale en el commit | `OBSERVADO` |
| `unknown` | SQL en texto, builders como pypika | se asume un rango: 0,14 ms | `SUPUESTO` |

Los otros efectos:

| Efecto | Parámetro | Etiqueta |
|---|---|---|
| `cpu` (nuevo en el extractor): hash o verificación de contraseña con pwdlib, passlib, bcrypt o argon2 | 110 ms (argon2id de pwdlib; bcrypt cost 12: 188 ms) | `CALIBRADO` (JAJ-46) |
| `cache` (GET/SET de Redis) | 0,03 ms | `CALIBRADO` |
| `background` (encolar en Redis) | 0,03 ms | `CALIBRADO` |
| `http`, `sdk`, `plugin` (servicio externo) | sin valor por defecto: lo ingresa el usuario | `SUPUESTO` |
| CPU base de FastAPI por request, endpoint `async` | 0,68 ms, medido a 200 req/s con asyncpg | `CALIBRADO` (JAJ-43) |
| CPU base de FastAPI por request, endpoint `def` | 2,1 ms, SQLModel + psycopg sostenido con carga | `CALIBRADO` (JAJ-46) |
| Latencia cliente ↔ API | 0,25 ms | `CALIBRADO` (JAJ-8) |

**De 1 núcleo del laptop a la nube (JAJ-46, JAJ-47).** Todos los tiempos de CPU del catálogo son de 1 núcleo del laptop de calibración (i7-13620H). Cada plan trae su procesador, y `deployment.api` y `deployment.db` llevan su `cpu_core_factor`. `checks` multiplica por ese factor la CPU de la API, las queries y la conexión tomada. El motor todavía no lo aplica (JAJ-48).

| Procesador | Planes | Factor | Etiqueta |
|---|---|---|---|
| Laptop de calibración | `local` | 1,0 | `CALIBRADO` |
| Graviton2 | Fargate ARM, `db.t4g.*`, Supabase (se asume) | 1,95 | `ESTIMADO`; en Supabase, `SUPUESTO` |
| Graviton3 | `db.m7g.*` | 1,55 | `ESTIMADO` (±30 %) |
| Graviton4 | (m8g, r8g) | 1,25 | `ESTIMADO` |

Las instancias con créditos (`db.t4g.micro` y `db.t4g.medium`) llevan `cpu_credits`. Con carga sostenida rinden su base de 10 % y 20 % por vCPU, o sea 0,2 y 0,4 vCPU, y `checks` usa esa base. En modo unlimited rinden los 2 vCPU y cobran el exceso.

**Qué pasa con una query que el AST no clasifica:** queda como `unknown`, con un valor por defecto `SUPUESTO`. Si después se usa un LLM, solo puede proponer la forma (por ejemplo "esto es un escaneo"). El número siempre sale del catálogo: el LLM nunca inventa números.

### Cómo se arma el costo de una request

* **Conexión tomada (`db_hold_ms`):** es la suma de las queries de la request. La sesión es por request (`Depends(get_db)`): se toma una conexión en la primera query y se suelta al cerrar la sesión.
  * La CPU pesada cuenta dentro de la conexión si corre en una dependencia que consulta la DB o en la misma función que consulta la DB. Pasa, por ejemplo, con `authenticate`, que lee el usuario y verifica la contraseña con la conexión tomada.
* **CPU de la API (`api_cpu_ms`):** la CPU base más la CPU pesada.
* **Ramas `if/else`:** el extractor guarda en qué rama está cada llamada. Si las dos ramas consultan la DB, el modelo usa la más cara (peor caso) y guarda la otra en `alternatives`. Por ejemplo, en `GET /items/` el superusuario hace un `COUNT(*)` de toda la tabla y el usuario normal un `COUNT` filtrado.
* **N+1:** el paso lleva un `repeat` con el largo de la lista. Es `SUPUESTO`, 20 por defecto.

## C. Las 3 preguntas al usuario

Formato: `answers/*.json`. En la app es un formulario de un paso, con plantillas y valores por defecto.

| Pregunta | Campos | Plantilla o valor por defecto | Etiqueta |
|---|---|---|---|
| **1. ¿Cuánto tráfico tienes?** | Una de dos formas: `{"mode": "mau", "mau": N, "profile": "ligero"\|"medio"\|"pesado"}` o `{"mode": "rps", "peak_rps": N}` | Perfiles de JAJ-11: 4×10, 8×17 y 12×25 sesiones/mes × requests/sesión. `K_hora` = 2,5 | `SUPUESTO` (declarado) |
| **2. ¿Dónde está desplegado?** | DB: `provider` + `plan` (Supabase micro…4xl, RDS t4g/m7g, local). API: `provider` (fargate, local), `replicas`, `vcpu`, `memory_gb` | Local en Docker con 1 réplica | Plan declarado; límites y precios `ESTIMADO` (JAJ-8 y JAJ-11) |
| **3. ¿Cuánto vale una venta?** | `ticket_usd`, `conversion` | US$45 y 2 % (JAJ-11) | `SUPUESTO`; si es el valor por defecto lleva `needs_review` |

Escenarios que se generan siempre:

* `pico_normal`: ×1.
* `cyberday`: ×20, el guion de la demo.

Opcionales (`overrides`):

* `endpoint_weights`: reparto del tráfico por endpoint. Por defecto, 85 % de lecturas en partes iguales entre los GET.
* `table_rows`: filas por entidad o tabla.
* `n_plus_one_list`: largo de las listas con N+1.
* `external_ms`: latencia de cada servicio externo.

Con modo `mau`, el pico se calcula como `usuarios/mes × sesiones/mes × requests/sesión / segundos del mes × K_hora`.

## D. Formato del modelo v1

Archivo único `branchpoint.model/v1`:

* `repo`: nombre y estadísticas de la extracción.
* `deployment.api`: réplicas, vCPU, workers, hilos, latencia y US$/mes.
* `deployment.db`: plan, vCPU, `max_connections`, pool por worker y US$/mes.
* `traffic`: entradas, pico y `scenarios`.
* `business`: ticket y conversión.
* `endpoints[]`: `steps` con `resource` (`db_connection`, `api_cpu`, `cache`, `external`), `time`, `repeat` opcional, `at` (archivo:línea) y `via`; además `alternatives`, `weight`, `db_hold_ms`, `api_cpu_ms` y `risks`.
* `checks`: cotas analíticas para revisar el modelo. No es la simulación: pool por ley de Little, CPU de la DB y CPU de la API contra el tráfico de cada escenario, y ventas en juego por hora.
* `assumptions`: todos los `SUPUESTO` de origen, agrupados por fuente.

Un número:

```json
{"value": 5.0, "unit": "ms", "label": "SUPUESTO",
 "source": "JAJ-8: escaneo completo de 1 M filas en 50 ms. COUNT(*) sin filtro recorre la tabla × 100000 filas de Item (...)",
 "date": "2026-11-21", "needs_review": true}
```

## Ejemplo: full-stack-fastapi-template

`results/full-stack-fastapi-template.model.json`, con respuestas ilustrativas: 100.000 usuarios/mes con perfil medio, Supabase Micro, 1 réplica en Fargate con 1 vCPU y ticket de US$30.

| | Valor | Etiqueta |
|---|---|---|
| Conexiones que puede abrir la app | 60 (4 workers × (5 + 10)) | `OBSERVADO` + `ESTIMADO` |
| Conexiones de Supabase Micro | 60: **al límite** | `ESTIMADO` |
| Pico normal / CyberDay | 13 / 262 req/s | `SUPUESTO` |
| Conexión tomada promedio por request, en la nube | 16,5 ms | `SUPUESTO` (por el hash y el `COUNT(*)`, × factor 1,95) |
| CPU de la API promedio por request, en la nube | 18,8 ms | `SUPUESTO` (por el hash de 110 ms, × factor 1,95) |
| Uso en CyberDay | CPU de la API 493 %, CPU de la DB 175 %, pool 7 % | `SUPUESTO` |
| Ventas en juego por hora en CyberDay | US$33.340 | `SUPUESTO` |
| Costo mensual | DB US$25 + API US$28,84 | `ESTIMADO` |

Lectura:

* El pool no es el problema, porque las queries son cortas.
* Lo primero que se satura es la CPU: la de la API por los hashes de login y registro, y la de la DB porque Supabase Micro tiene media vCPU.
* Si alguien sube los workers para ganar CPU, el pool pasa el límite de conexiones de Supabase. Es el caso para recomendar el pooler.

`results/fastapi-realworld-example-app.model.json` usa `answers/ejemplo-rps.json` (modo `rps`, RDS). Muestra los N+1 con su `repeat`: `GET /articles` hace un rango, búsquedas y COUNT por cada artículo de la lista.

## Limitaciones conocidas

* **Índices:** el AST no sabe si la columna del filtro tiene índice. `lookup` y `range` lo asumen (`ESTIMADO`). Se podría leer `index=True` en los modelos.
* **Funciones alcanzadas por varios caminos:** si una función se alcanza dos veces en la misma request, se cuenta una sola vez, porque el grafo de llamadas visita cada función una vez.
* **Ramas en el sitio de la llamada:** las ramas sí se propagan a las funciones llamadas, pero una función alcanzada desde dos ramas toma la rama del primer camino.
* **Orden de los pasos y tiempo con la conexión tomada:** son aproximados. No se modela la CPU entre queries, salvo la pesada.
* **Tiempos de la DB:** están medidos con 1 CPU local y caché caliente. El paso a la nube es un factor por procesador (JAJ-46, `ESTIMADO`); el disco de la nube sigue sin medir.
* **Reparto del tráfico:** por defecto es uniforme dentro de las lecturas y dentro de las escrituras. Para la demo conviene declararlo.

## Archivos

* `build_model.py`: arma el modelo v1 (repo + catálogo + respuestas).
* `catalog.json`: números por defecto con su procedencia (JAJ-8, JAJ-11, JAJ-43).
* `answers/`: respuestas de ejemplo a las 3 preguntas.
* `results/*.model.json`: modelos de ejemplo.
* Cambios en `spikes/jaj-7-ingestion/extract.py`:
  * Cada efecto ahora trae su forma (`shape`), la rama en que está (`branch`) e `in_loop`.
  * Hay un efecto `cpu` nuevo para el hash de contraseñas.
  * Cada endpoint indica si es `async`.
