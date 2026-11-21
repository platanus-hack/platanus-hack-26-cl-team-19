# Spike JAJ-7: extraer un grafo de arquitectura de un repo FastAPI real

Issue: [JAJ-7](https://linear.app/jajathom/issue/JAJ-7/podemos-extraer-un-grafo-util-de-un-repo-fastapi-real-en-menos-de-1)

## Resultado en 5 líneas

1. **Decisión: SIGUE.** La ingesta automática puede ser el flujo principal; el canvas manual queda para corregir y completar.
2. En 3 repos que no escribimos, el extractor encontró **332 de 332 endpoints**. **328 tienen sus accesos a DB**, con archivo:línea, y 325 tienen además la entidad o tabla. Corre en **0,03 s a 1,5 s**, muy por debajo del minuto.
3. Detecta **N+1 reales**: 3 en realworld (el caso clásico de "listar artículos → una query de tags por artículo") y 88 sitios en Dispatch. Revisé 6 a mano y los 6 eran reales.
4. Lo que el AST no ve: los destinos de los plugins dinámicos (los marca como "destino dinámico"), las librerías externas fuera de la lista (por ejemplo el envío de email con `emails`), SQL armado con pypika, y las dependencias declaradas a nivel de router. Esto es lo que tendría que completar el LLM.
5. Es determinista: dos corridas dan exactamente el mismo grafo. No se probó el paso con LLM porque no había API key; queda pendiente.

## Cómo correrlo

```bash
python3 extract.py <ruta-al-repo> -o salida.json
```

Requiere solo Python 3.12 (stdlib). **No importa ni ejecuta** el código analizado: solo lo parsea con `ast`.

## Repos probados

| Repo | Commit | Archivos .py | Endpoints encontrados | Con DB | Con entidad | Riesgos | Tiempo |
|---|---|---|---|---|---|---|---|
| [fastapi/full-stack-fastapi-template](https://github.com/fastapi/full-stack-fastapi-template) | `77e550a` | 21 | 23 / 23 | 22 | 21 | 0 | 0,03 s |
| [nsidnev/fastapi-realworld-example-app](https://github.com/nsidnev/fastapi-realworld-example-app) | `029eb77` | 70 | 19 / 19 | 19 | 19 | 3 N+1 | 0,05 s |
| [Netflix/dispatch](https://github.com/Netflix/dispatch) | `dd2837e` | 651 | 290 / 290 | 287 | 285 | 88 sitios N+1 | 1,5 s |

"Encontrados" se compara contra el conteo de decoradores `@router.<método>` con grep. Los tiempos son del extractor en un laptop; el `git clone --depth 1` va aparte y no se midió en detalle (tomó segundos).

## Verificación manual

- **Template (23 endpoints):** revisé todos. Los paths completos (prefijos de `include_router`) están correctos. El único endpoint sin DB es `/utils/health-check/`, y es correcto que no tenga. Falla: no detecta el envío de email de `/password-recovery` ni el de `/utils/test-email/` (usan la librería `emails`, que no está en la lista).
- **Realworld (19):** todos usan DB, ya sea por el repositorio o por la autenticación, y es correcto. Las lecturas y escrituras salen de leer los archivos `.sql` de aiosql (`-- name:`), no solo del AST.
- **Dispatch (muestra de 10 al azar):** 10 de 10 tienen el path correcto (`/api/v1/{organization}/...`, que pasa por `app.mount` y 3 niveles de `include_router`) y los accesos a DB del handler correctos.
- **N+1:** 6 de 6 sitios revisados eran una query por iteración (comprensiones o `for` que llaman a `service.get(...)` o a `get_or_create`).

## Qué detecta

Por cada endpoint: método, path completo, handler con archivo:línea, las funciones que alcanza por el grafo de llamadas, y los efectos con archivo:línea y la cadena de llamadas (`via`):

- `db`: lectura o escritura, con la entidad (`select(Item)`, `query(Tag)`, `session.get(User, id)`) o la tabla (aiosql).
- `http` y `sdk`: `requests`, `httpx` y `aiohttp`, y una lista de SDKs (boto3, slack_sdk, stripe, openai...), marcando las llamadas sin `timeout`.
- `cache`: receptores con nombre `redis` o `cache`.
- `background`: `.delay()`, `.apply_async()` y `BackgroundTasks.add_task`.
- `plugin`: `x.instance.metodo()`, donde el destino se resuelve en runtime.
- `cpu`: hash o verificación de contraseñas con pwdlib, passlib, bcrypt o argon2.

Agregado en [JAJ-45](../jaj-45-numeros/README.md), para asignarle a cada efecto un número del catálogo:
- `shape`: la forma de cada acceso a DB (`pk`, `lookup`, `range`, `count`, `count_all`, `scan`, `commit`, `stage`, `unknown`). Se deduce de la cadena del statement o del SQL de aiosql.
- `branch`: las ramas `if/else` que contienen la llamada.
- `in_loop`: si la llamada se repite dentro de un loop.
- `async`: si el endpoint es `async def`.

Cómo resuelve las llamadas:
- Imports absolutos y relativos.
- Métodos por el tipo anotado de los parámetros (`repo: ArticlesRepository`).
- Atributos `self.x` asignados en `__init__`.
- Herencia.
- `Depends(f)`, `Depends(factory())` y los alias `Annotated[..., Depends(f)]`.
- `dependencies=[...]` del decorador.

Riesgos que marca:
- **N+1:** un acceso a DB alcanzable desde un loop o una comprensión. Se reporta en la línea del loop, una vez por sitio.
- **HTTP sin timeout:** solo para `requests`.
- **Llamada bloqueante en `async def`.**

En estos repos no aparecieron llamadas HTTP ni bloqueantes, así que esas dos reglas no quedaron validadas.

## Limitaciones conocidas (candidatas para el LLM)

- **Plugins o despacho dinámico:** Dispatch hace sus llamadas externas por `plugin.instance.create(...)`. Las marcamos como externas con destino desconocido (25 endpoints).
- **Routers incluidos dinámicamente:** los 4 endpoints `/slack/*` de Dispatch se encuentran, pero sin el prefijo final.
- **Dependencias a nivel de router** (`APIRouter(dependencies=[...])`): no se propagan.
- **SQL armado con builders** (pypika en realworld): el acceso a DB se detecta, pero no la tabla.
- **Heurísticas por nombre:** un receptor que se llame `db`, `session` o `conn` cuenta como DB, y uno que se llame `redis` o `cache` cuenta como caché. Puede haber falsos positivos con nombres raros.
- **Sintaxis de Python 3.14** (`except A, B:` sin paréntesis): el template ya la usa. Se reescribe antes de parsear con un regex, y conviene parsear con un Python ≥ 3.14.

## Archivos

- `extract.py`: el extractor, un solo archivo y solo con la stdlib.
- `results/*.json`: el grafo de salida del template y de realworld. El de Dispatch pesa 1,3 MB y se regenera con el comando de arriba.
