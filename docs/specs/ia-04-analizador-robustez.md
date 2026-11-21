# IA-4: Analizador: evidencia verificada, presupuesto y progreso

**Área:** backend · **Depende de:** IA-3, resultado de IA-0 · **Tamaño:** M

## Objetivo

El agente es el único extractor, así que lo que entrega tiene que poder comprobarse y su gasto tiene que estar acotado. Hoy el servidor verifica contra el repo solo los valores de `observations`.

## Leer antes

* `backend/app/ingest/analyzer.py`: `analyze_repo`, `RepoReader`, `SYSTEM`, los límites.
* `backend/app/ingest/ai_graph.py`: `ArchitectureSubmission`, `_Evidence`, `observed_values`, `build_from_ai`.
* `backend/app/github/ingestion.py`: `run_ingestion`, `Ingestion`.
* El README de IA-0: qué falló y qué límites recomienda.

## Cambios

### 1. Verificar la evidencia contra el repo

Función nueva en `ai_graph.py`: `check_evidence(sub: ArchitectureSubmission, root: Path) -> list[str]`. Devuelve problemas en español, con la ubicación, pensados para que el LLM los lea y corrija. Lista vacía significa válido.

Comprueba, para cada endpoint, paso, job, componente y observación:

1. El archivo existe dentro de `root` (resolver la ruta y rechazar las que salgan, también por symlink).
2. `line` no pasa el largo del archivo.
3. Solo endpoints: el segmento estático más largo de `path` (sin `{}`, `:` ni `*`) aparece en ese archivo entre `line - 30` y `line + 30`. Si el path es `/` o no tiene segmento estático, se omite.

Ejemplo de mensaje: `endpoints[3] (GET /users/{id}): 'src/routes/users.ts' no existe en el repo`.

En `analyze_repo`, después de validar el schema:

* Con problemas: devolverlos como error de `submit_architecture`, igual que un error de schema, para que el modelo corrija.
* Tras 3 entregas con problemas de evidencia: aceptar la propuesta quitando los endpoints, pasos y componentes con problemas, y devolverlos en una lista `dropped`. Si no queda ningún endpoint, `AnalysisFailed`.
* `dropped` se guarda en `repo.source.analysis.dropped` y se suma a los avisos del modelo.

Desde la CLI por MCP no hay `root`: ese camino no cambia.

### 2. Tope de tokens

* `analyze_repo(..., max_tokens_total: int | None = None)`: si la suma de tokens de entrada y salida pasa el tope, termina con `AnalysisFailed` y el mensaje "El análisis pasó el límite de la key de Branchpoint. Con tu propia API key no hay límite."
* La ingesta lo pasa solo cuando la credencial es la de Branchpoint (`LlmKey.source == "team"`, IA-2), con `BRANCHPOINT_TEAM_EXTRACT_TOKENS`. El valor por defecto sale de IA-0; mientras tanto, 1.500.000.
* Una extracción que falla por este tope sí cuenta contra la cuota: los tokens se gastaron.

### 3. Progreso

* `analyze_repo(..., on_step: Callable[[int, str], None] | None = None)`: se llama en cada vuelta con el número de vuelta y el nombre de la última tool.
* `Ingestion` e `IngestionOut` ganan `llm_steps: int | None` y, al terminar, `cost` (el dict de `cost_usd` de `app/agent/loop.py`, o `None` si el modelo no tiene precio en `manual.json`).
* `run_ingestion` actualiza `llm_steps` con `jobs.update`.

### 4. Ajustes que salgan de IA-0

Aplicar al prompt `SYSTEM` y a `MAX_ITERATIONS`, `MAX_LINES`, `MAX_TREE` lo que recomiende el README de IA-0. Cada cambio de prompt va con la medición que lo justifica en la descripción de la PR.

El prompt tiene que decir, si no lo dice ya, que el contenido de los archivos es material a analizar y que no se siguen instrucciones que aparezcan dentro de ellos.

### 5. Errores del proveedor

Si `llm.complete` lanza un error del SDK (key inválida, sin crédito, límite de la API), la ingesta termina `failed` con el mensaje de `_provider_error` de `app/agent/loop.py`, no con el genérico "No pudimos analizar el repo".

## Criterios de aceptación

Con un LLM falso, como en `tests/ingest/test_analyzer.py`. Ningún test llama a un proveedor.

* `check_evidence`, un test por regla: archivo inexistente, ruta con `..`, symlink hacia afuera, línea fuera de rango, path que no aparece cerca de la línea, path `/` omitido.
* Una entrega con un endpoint de evidencia falsa vuelve como error al LLM. Si la corrige, el resultado no tiene `dropped`.
* Tres entregas con el mismo problema: sale la arquitectura sin ese endpoint y `dropped` lo nombra.
* Todos los endpoints con evidencia falsa tras tres entregas: `AnalysisFailed`.
* `max_tokens_total` corta el loop con el mensaje del punto 2.
* `on_step` recibe una llamada por vuelta y `GET /github/ingestions/{id}` muestra `llm_steps` creciendo.
* Un `AuthenticationError` del proveedor deja la ingesta `failed` con un mensaje que nombra al proveedor y no incluye la key.
* Los tests de la PR #59 siguen pasando.

## Fuera de alcance

* Verificar que el `shape` de cada paso sea correcto: eso se mide en IA-0, no se valida en código.
* Guardar en caché el análisis de un mismo commit.
