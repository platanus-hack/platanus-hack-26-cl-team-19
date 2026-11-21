# IA-3: Contrato `branchpoint.graph/v1` y su validador

**Área:** backend · **Depende de:** nada · **Tamaño:** M · **Bloquea:** IA-4, IA-5, IA-10

## Objetivo

Un formato único para "lo que se extrajo de un repo", que entreguen tanto el extractor por AST como el agente LLM. Sin números de rendimiento. Con evidencia verificable.

## Leer antes

* `backend/app/ingest/extract.py`: `run()` (al final) y `Effect`. Es la salida de hoy.
* `backend/app/ingest/build_model.py`: `build()` y `step_for()`. Es quien la consume.
* `backend/app/ingest/iac.py`: `Service`, `Findings`.
* [ADR 0002](../adr/0002-extraccion-con-llm-para-repos-no-fastapi.md).

## Contrato

Módulo nuevo `backend/app/ingest/graph.py`, con modelos Pydantic y `extra="forbid"`.

```python
Origin = Literal["ast", "iac", "llm"]
ComponentKind = Literal["service", "db", "cache", "queue", "worker", "external", "proxy", "storage"]
EffectKind = Literal["db", "cache", "http", "sdk", "background", "cpu"]
DbShape = Literal["pk", "lookup", "range", "count", "count_all", "scan", "stage", "commit", "unknown"]

class Evidence:        file: str; line: int (>= 1)
class Component:       id: str; kind: ComponentKind; name: str; repo: str; technology: str | None
                       evidence: Evidence; origin: Origin
class Edge:            source: str; target: str   # ids de Component
                       kind: Literal["calls", "reads", "writes", "publishes", "consumes"]
                       evidence: Evidence; origin: Origin
class Effect:          kind: EffectKind; detail: str; shape: DbShape | str = ""
                       target: str | None      # id del Component que toca
                       in_loop: bool = False; evidence: Evidence
class Endpoint:        service: str            # id de un Component con kind="service"
                       method: str; path: str; handler: str; is_async: bool | None
                       effects: list[Effect]; evidence: Evidence; origin: Origin
class ConfigValue:     service: str; field: Literal["workers", "pool_size", "max_overflow", "pool_timeout_s"]
                       value: float; evidence: Evidence; origin: Origin
class Graph:           schema: Literal["branchpoint.graph/v1"]
                       repos: list[str]; components: list[Component]; edges: list[Edge]
                       endpoints: list[Endpoint]; config: list[ConfigValue]; warnings: list[str]
```

Reglas:

* `Evidence.file` es relativo a la raíz del repo, con `/`. Con varios repos lleva el prefijo `<repo>/`.
* `shape` de un efecto `db` usa `DbShape`. De un efecto `cpu`, una clave de `cpu_steps` del catálogo (`app/catalog/catalog.json`). En el resto va vacío.
* Los ids de `Component` son únicos. Todo `Edge.source`, `Edge.target`, `Endpoint.service`, `Effect.target` y `ConfigValue.service` apunta a un id que existe.
* No hay campos para latencias, tráfico ni costos.

## Validador

`validate_graph(graph: Graph, roots: dict[str, Path]) -> list[str]`, donde `roots` mapea nombre de repo a carpeta. Devuelve una lista de problemas en español, pensados para que un LLM los lea y corrija. Lista vacía significa válido.

Comprueba:

1. Referencias entre ids (regla de arriba).
2. Cada `Evidence`: el archivo existe dentro de la raíz (resolver y rechazar rutas que salgan de ella) y `line` no pasa el largo del archivo.
3. Cada `Endpoint`: algún segmento estático de `path` (el más largo sin `{}` ni `:`) aparece en el archivo citado entre `line - 30` y `line + 30`. Si el path es `/`, se omite.
4. Cada `ConfigValue`: el número aparece textualmente en la línea citada.
5. Pares duplicados `(service, method, path)`.

Mensajes con la ubicación: `endpoints[3]: 'src/routes/users.ts' no existe en el repo 'api'`.

## Adaptador del AST

`from_ast(graph: dict, iac: dict, repo: str) -> Graph`: convierte la salida de `extract.run()` y `scan_deployment().to_dict()`.

* Un `Component` `service` por el repo. Los servicios de `iac` con rol DB, caché, cola o worker pasan a componentes con `origin="iac"`.
* Si hay efectos `db` y `iac` no trae DB, crear un componente `db` con `origin="ast"` y la evidencia del primer efecto.
* Efectos `plugin` del AST pasan a `sdk`.
* Todo lo demás lleva `origin="ast"`.

## Criterios de aceptación

* Test: `from_ast` sobre `tests/fixtures` o el sample de `fastapi-realworld-example-app` da un `Graph` con 19 endpoints que pasa `validate_graph` sin problemas contra el repo. Si el repo no está disponible en CI, armar un repo mínimo de FastAPI en `tmp_path`.
* Tests del validador, uno por regla: archivo inexistente, ruta con `..`, línea fuera de rango, path que no aparece cerca de la línea, `ConfigValue` cuyo número no está en la línea, id inexistente, endpoint duplicado.
* `Graph.model_json_schema()` no contiene ningún campo numérico de rendimiento. Test que lo fija: las únicas propiedades numéricas son `line` y `value`.

## Fuera de alcance

* Cambiar `build_model.py` para consumir `Graph`: es IA-5.
* El extractor LLM: es IA-4.
