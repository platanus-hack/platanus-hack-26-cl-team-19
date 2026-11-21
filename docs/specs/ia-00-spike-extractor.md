# IA-0: Spike del extractor agente

**Área:** backend · **Depende de:** nada · **Tamaño:** S (medio día) · **Bloquea:** IA-4

## Pregunta

¿Un agente con `list_dir`, `read_file` y `grep` extrae un grafo útil de un repo que no es FastAPI, en un tiempo y a un costo aceptables?

## Qué hacer

Un script desechable en `spikes/ia-0-extractor/` (no en `backend/app`). Puede reutilizar `AnthropicLLM` y `OpenAILLM` importándolos desde `backend/`.

1. Implementar tres tools de solo lectura sobre una carpeta local:
   * `list_dir(path)`: entradas de un directorio, sin `.git`, `node_modules`, `.venv`, `dist`, `build`.
   * `read_file(path, start, end)`: máximo 400 líneas por llamada, con número de línea.
   * `grep(pattern, glob?)`: máximo 100 coincidencias, como `archivo:línea: texto`.
2. Una tool `submit_graph(graph)` que termina el loop. Usar la forma de [IA-3](ia-03-grafo-v1.md), aunque sea sin validar.
3. Un loop con máximo 40 vueltas. Registrar tokens de entrada, de salida y de caché, vueltas y segundos.
4. Correrlo sobre tres repos:
   * `fastapi-realworld-example-app` (hay modelo de referencia en `backend/app/samples/`): comparar endpoints contra el AST.
   * Un repo Node (Express o NestJS) con Docker Compose.
   * Un repo de otro lenguaje (Django, Go o Rails).
5. Para los repos sin referencia, contar los endpoints a mano (con `grep` de las rutas) para tener el denominador.
6. Repetir cada repo dos veces para ver cuánto cambia el resultado.

## Qué medir

| Medida | Umbral propuesto |
|---|---|
| Endpoints encontrados / endpoints reales | ≥ 80 % |
| Endpoints inventados (no existen en el repo) | 0 |
| Evidencia válida (el archivo existe y la línea contiene la ruta o la llamada) | ≥ 95 % |
| Tiempo total por repo | < 3 min |
| Costo por repo con la tabla de `app/costs/prices/manual.json` | < US$ 1 |
| Componentes de infraestructura (DB, caché, cola) detectados | todos los del Compose |

## Entregable

`spikes/ia-0-extractor/README.md` con la tabla de resultados por repo y proveedor, el prompt de sistema usado y una conclusión: **sigue**, **sigue con reservas** (qué recortar) o **no sigue**.

Si no cumple el umbral de endpoints pero sí detecta los componentes, IA-4 se recorta a componentes y conexiones: sirve para el diagrama y el proyecto no se simula.

## Fuera de alcance

* Integrarlo a la ingesta, la cuota o la UI.
* Armar `model/v1`.
