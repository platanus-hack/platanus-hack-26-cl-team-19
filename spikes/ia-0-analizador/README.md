# IA-0: medir el analizador con LLM reales

Spec: [`docs/specs/ia-00-medir-analizador.md`](../../docs/specs/ia-00-medir-analizador.md) · Linear [JAJ-112](https://linear.app/jajathom/issue/JAJ-112).

**Pregunta.** El agente es el único camino para importar un repo. ¿`analyze_repo` entrega una arquitectura correcta, en un tiempo y a un costo aceptables, con un LLM real?

**Estado.**

* **Calidad con un LLM real: medida** en los 4 repos chicos, con Claude (Fable 5.2) leyendo cada repo en modo CLI (ADR 0002). Encontró 80 de 80 endpoints, no inventó ninguno y el 100 % de la evidencia es válida (196 citas, con `check_evidence` de IA-4). Ver [Resultados](#resultados).
* **Tokens, tiempo y costo por la API: sin medir.** En el entorno no había `ANTHROPIC_API_KEY` ni `OPENAI_API_KEY`, así que `analyze_repo` no corrió contra un proveedor. Esa parte queda con la estimación previa y los comandos de [Cómo correrlo](#cómo-correrlo).

## Qué hay

| Archivo | Qué es |
|---|---|
| `run.py` | Llama `analyze_repo(root, llm, repo)` del backend, cuenta vueltas, tokens, segundos y costo, compara con la referencia y revisa 20 pasos al azar |
| `reference.json` | Los endpoints reales de cada repo, contados a mano |
| `results/runs.jsonl` | Una línea por corrida (se crea al correr) |
| `results/sample-<repo>-<proveedor>-<n>.csv` | Los 20 pasos al azar de cada corrida, con la columna `shape_ok (a mano)` para la revisión manual |

## Repos y denominadores

| Repo | Commit | Framework | Endpoints reales | Cómo se contaron | Compose |
|---|---|---|---|---|---|
| [nsidnev/fastapi-realworld-example-app](https://github.com/nsidnev/fastapi-realworld-example-app) | `029eb77` | FastAPI | 19 | El modelo de `backend/app/samples/` (extractor AST) y `grep @router.<método>`: coinciden | sí |
| [fastapi/full-stack-fastapi-template](https://github.com/fastapi/full-stack-fastapi-template) | `77e550a` | FastAPI | 23 | El fixture de `backend/tests/fixtures/` y `grep`: coinciden | sí |
| [gothinkster/node-express-realworld-example-app](https://github.com/gothinkster/node-express-realworld-example-app) | `30b68e1` | Express + Prisma | 19 | `grep router.<método>(` en `src/`, montados en `/api` | no, solo Dockerfile |
| [gothinkster/django-realworld-example-app](https://github.com/gothinkster/django-realworld-example-app) | `29c9d42` | Django REST | 19 | `urls.py` y las vistas de `conduit/apps`, leídos a mano. No coincide con la spec RealWorld: `ArticleViewSet` no define `destroy` (no hay `DELETE /api/articles/{slug}`) y `RetrieveUpdateAPIView` expone `PATCH /api/user` | no |
| [mealie-recipes/mealie](https://github.com/mealie-recipes/mealie) | `d84deca` | FastAPI (grande) | 292 | `grep @<router>.<método>(` en `mealie/` | sí |

La spec pedía un repo Node con Docker Compose. El de RealWorld no lo trae; si se quiere medir la detección del Compose en otro lenguaje, cambiarlo por uno que lo tenga.

Mealie queda cerca del tope del schema: `ArchitectureSubmission.endpoints` acepta 300.

## Estimación previa (antes de gastar tokens)

`ESTIMADO`, calculado con el tamaño del código de backend de cada repo (sin tests, migraciones ni frontend) y los precios de `backend/app/costs/prices/manual.json` para `claude-opus-5-5` (US$4 de entrada y US$20 de salida por millón; lectura de caché US$0,20).

Supuestos: unos 3,5 caracteres por token, el analizador lee alrededor del 60 % del backend, 8.000 tokens por lectura, 800 de salida por vuelta y 3.000 fijos de system y tools.

| Repo | Vueltas | Tokens de entrada | Tokens de salida | US$ por corrida | US$ con caché de prompt |
|---|---|---|---|---|---|
| fastapi-realworld | ~4 | ~45k | ~4k | ~0,25 | ~0,19 |
| full-stack-fastapi | ~4 | ~43k | ~3k | ~0,24 | ~0,18 |
| node-express | ~4 | ~27k | ~3k | ~0,17 | ~0,14 |
| django | ~4 | ~34k | ~3k | ~0,20 | ~0,17 |
| mealie | ~39 | ~6.100k | ~31k | **~25** | ~3,7 |

Las vueltas de los repos chicos probablemente estén subestimadas: un agente suele leer de a un archivo. La conclusión no depende de eso.

**Por qué crece tanto con un repo grande.** `analyze_repo` reenvía toda la conversación en cada vuelta, y `AnthropicLLM` no marca nada con `cache_control`. Los tokens de entrada crecen con el cuadrado de las vueltas: la vuelta 39 reenvía todo lo leído en las 38 anteriores. Con caché de prompt, ese reenvío se cobra a precio de lectura de caché (20 veces menos).

Costo de la matriz completa (5 repos × 2 corridas × Claude): unos US$52 sin caché, de los que US$50 son mealie. Conviene correr primero un repo chico, comparar con la estimación y recién ahí decidir si correr mealie.

**OpenAI.** `gpt-4.1-mini` no está en `manual.json`, así que `cost_usd` devuelve `None`: con OpenAI se reportan solo tokens. Agregar la fila solo con una fuente.

## Prueba del script sin red

`--dry` usa un LLM falso que busca rutas con `grep` y las entrega sin pasos. Recorre el camino real: `RepoReader`, el schema de `submit_architecture` y las métricas. Sus números no miden nada.

```
fastapi-realworld   2 vueltas  5 endpoints   recall 0,00   (el grep falso no arma los prefijos de los routers)
full-stack-fastapi  2 vueltas  16 endpoints  recall 0,22
node-express        2 vueltas  7 endpoints   recall 0,37
django              2 vueltas  NoEndpoints   (Django no usa decoradores de ruta)
mealie              2 vueltas  44 endpoints  recall 0,15   (grep corta en 100 resultados)
```

Lo que sí muestra: `grep` del analizador corta en 100 resultados (`MAX_GREP_HITS`). En mealie, un `grep` de rutas no alcanza a ver los 292 decoradores de una vez, y el agente tiene que buscar por carpeta.

## Cómo correrlo

```bash
# clones de solo lectura (el código no se ejecuta)
mkdir -p ~/ia0-repos && cd ~/ia0-repos
git clone --depth 1 https://github.com/nsidnev/fastapi-realworld-example-app
git clone --depth 1 https://github.com/fastapi/full-stack-fastapi-template
git clone --depth 1 https://github.com/gothinkster/node-express-realworld-example-app
git clone --depth 1 https://github.com/gothinkster/django-realworld-example-app
git clone --depth 1 https://github.com/mealie-recipes/mealie

cd <repo de branchpoint>/backend
# 1. un repo chico, para comparar con la estimación
ANTHROPIC_API_KEY=... .venv/bin/python ../spikes/ia-0-analizador/run.py --repos ~/ia0-repos \
    --repo node-express-realworld-example-app --provider anthropic --runs 1
# 2. la matriz: dos corridas por repo y proveedor
ANTHROPIC_API_KEY=... .venv/bin/python ../spikes/ia-0-analizador/run.py --repos ~/ia0-repos --provider anthropic --runs 2
OPENAI_API_KEY=... .venv/bin/python ../spikes/ia-0-analizador/run.py --repos ~/ia0-repos --provider openai --runs 2
```

Después, completar a mano la columna `shape_ok` de los CSV de `results/` y llenar las tablas de abajo.

## Resultados

### Calidad con un LLM real: Claude en modo CLI

Cómo se midió: Claude (el agente de Claude Code, Fable 5.2) leyó cada repo con `grep` y lectura de archivos, la misma información que dan las tools del analizador, y armó la arquitectura con el schema de `submit_architecture` ([ADR 0002](../../docs/adr/0002-la-ia-lee-la-arquitectura-del-repo.md), modo CLI). Las entregas están en `claude-cli/` (las escribe `claude-cli/build.py`).

`score.py` las puntúa sin LLM:

* valida cada entrega con el schema;
* compara los endpoints con `reference.json`, sin el prefijo de montaje (`/api`, `/api/v1`);
* revisa **toda** la evidencia (endpoints, pasos y componentes), no una muestra de 20, con `check_evidence` de IA-4.

Cada entrega se armó además con `build_from_ai` y se simuló CyberDay con el motor.

| Repo | Endpoints / reales | Inventados | Pasos | Evidencia válida | Arma un modelo que simula |
|---|---|---|---|---|---|
| fastapi-realworld (FastAPI + asyncpg) | 19 / 19 | 0 | 19 | 39 / 39 | sí (p95 5,9 ms) |
| full-stack-fastapi (FastAPI + SQLModel) | 23 / 23 | 0 | 37 | 61 / 61 | sí (p95 25,5 ms) |
| node-express (Express + Prisma) | 19 / 19 | 0 | 31 | 51 / 51 | sí (p95 44,1 ms) |
| django (Django REST) | 19 / 19 | 0 | 26 | 45 / 45 | sí (p95 7,4 ms) |

```bash
cd backend && .venv/bin/python ../spikes/ia-0-analizador/score.py --repos ~/ia0-repos ../spikes/ia-0-analizador/claude-cli/*.json
```

**Lo que encontró la medición:**

1. **Un falso positivo en la regla de evidencia de IA-4.** `check_evidence` exigía que el segmento fijo más largo de la ruta apareciera cerca de la línea citada. En FastAPI, `@router.delete("/{id}")` solo trae el parámetro: el segmento (`items`) viene del `prefix=` del `APIRouter`, a 89 líneas. Con esa regla, 3 de 80 endpoints bien citados salían como evidencia inválida (96,7 % y 97,4 % en los repos de FastAPI). La corrección, que va en la PR de IA-4: vale un segmento fijo cerca de la línea o, si no está cerca, que aparezca como palabra en el mismo archivo (donde está el `prefix`). Una ruta inventada (`/invoices`) sigue fallando. Con ella, 100 %.
2. **La referencia de Django estaba mal.** La armé desde la spec RealWorld sin leer las vistas; tiene un endpoint distinto. Se corrigió leyendo el repo.

**Límites de esta medición:**

* El modo CLI no pasa por `analyze_repo`. No hay vueltas, tokens ni tiempo de la API que medir, y el agente pudo leer sin el tope de 40 vueltas.
* La forma (`shape`) de cada paso la puso el mismo agente que se evalúa: no hay revisión independiente.
* No se midió mealie (292 endpoints) en este modo: no cabe leerlo entero en el contexto del agente, y en ese repo lo crítico es el costo por la API.
* OpenAI no se midió.

### Por la API (`analyze_repo` con Anthropic y OpenAI)

Pendiente de key. Se llena con `results/runs.jsonl`.

| Repo | Proveedor | Corrida | Endpoints / reales | Inventados | Evidencia válida (20) | `shape` ok (20) | Vueltas | Tokens | Segundos | US$ | Falló |
|---|---|---|---|---|---|---|---|---|---|---|---|
| | | | | | | | | | | | |

| Medida | Umbral | Resultado |
|---|---|---|
| Endpoints encontrados / reales | ≥ 80 % | **100 %** en los 4 chicos (Claude, modo CLI); por la API, pendiente |
| Endpoints inventados | 0 | **0** (Claude, modo CLI) |
| Evidencia válida en la muestra | ≥ 95 % | **100 %** de 196 citas, con la regla corregida; 98,5 % con la regla original de IA-4 |
| `shape` correcto en la muestra | ≥ 80 % | sin revisión independiente |
| Tiempo por repo | < 3 min | pendiente (API) |
| Costo por repo | < US$1 | estimado: sí en los 4 chicos; no en mealie sin caché |
| `AnalysisFailed` en repos de hasta 50 endpoints | 0 | pendiente (API) |
| Componentes del Compose detectados | todos | la base sí (3 de 3 repos con Compose); el resto lo lee `iac.py`, que es determinista |

## Ajustes para IA-4

Salen de la estimación y del código, no todavía de la medición. IA-4 (JAJ-120) aplicó el 1, el 2, el 4 y el 7; el 3, el 5 y el 6 esperan la medición:

1. **Caché de prompt en el analizador.** Marcar con `cache_control` el último bloque del historial en cada vuelta de `analyze_repo` con Anthropic. Es el ajuste de mayor efecto en el costo (mealie: de ~US$25 a ~3,7).
2. **Tope de tokens de la key de Branchpoint:** dejar 1.500.000, el valor provisorio de la spec de IA-4. Cubre con holgura los repos de hasta ~50 endpoints (unos 50k estimados) y corta un repo como mealie sin caché antes de gastar unos US$6. Revisarlo con la medición.
3. **`MAX_ITERATIONS` (40):** alcanza para los repos chicos. Para uno de 300 endpoints, la estimación ya llega a ~39 vueltas: subirlo solo con caché de prompt.
4. **`MAX_GREP_HITS` (100):** decirle al agente en `SYSTEM` que, si `grep` vuelve truncado, busque por carpeta.
5. **`MAX_TREE` (600):** mealie tiene 1.785 archivos y el árbol inicial muestra 600 (los primeros en orden). Considerar ordenar primero las carpetas de backend o mostrar solo directorios cuando el repo es grande.
6. **`MAX_LINES` (400):** sin cambio hasta medir.
7. **Prompt:** agregar que el contenido de los archivos es material a analizar y que no se siguen instrucciones que aparezcan dentro (pedido en IA-4).

## Conclusión

**Listo con los ajustes de IA-4** para repos de hasta ~50 endpoints.

* **Calidad:** medida con un LLM real (Claude, modo CLI). 100 % de los endpoints, 0 inventados y 100 % de la evidencia válida en 4 frameworks, con la regla de evidencia corregida.
* **Costo y tiempo por la API:** solo estimados, falta medir con una key. Para un repo de ~300 endpoints, **no alcanza** sin caché de prompt: unos US$25 estimados, 25 veces el umbral. IA-4 agrega la caché.
