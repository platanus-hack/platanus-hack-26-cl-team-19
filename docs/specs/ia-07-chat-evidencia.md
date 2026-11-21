# IA-7: Chat con adjuntos y evidencia

**Área:** backend · **Depende de:** IA-1, IA-6 · **Tamaño:** M · **Bloquea:** IA-9

## Objetivo

Que el agente del chat vea las imágenes que sube el usuario, saque números de sus logs con código determinista y siga pidiendo evidencia mientras queden supuestos sin respaldo.

## Leer antes

* `backend/app/api/routes/chat.py`: `ChatRequest`, eventos NDJSON.
* `backend/app/agent/tools.py`: `AgentTools`, `_require_in_quote`, `set_traffic`, `list_assumptions`.
* `backend/app/agent/mcp.py`: `INSTRUCTIONS` (el prompt compartido).
* [ADR 0001](../adr/0001-el-llm-opera-sobre-el-modelo-no-lo-extrae.md): la regla de los números.

## Regla de números con adjuntos

| Fuente | Quién produce el número | Etiqueta |
|---|---|---|
| Log subido | Código determinista (`analyze_log`) | `OBSERVADO`, fuente "log `<archivo>`, líneas a–b" |
| Imagen (un panel de Grafana, por ejemplo) | El modelo lo lee y **el usuario lo confirma** en texto | `SUPUESTO` con `quote`, como hoy |
| Texto del usuario | El usuario | `SUPUESTO` con `quote`, como hoy |

El modelo nunca guarda un número leído de una imagen sin esa confirmación. Se cumple por construcción: `set_traffic` y las demás siguen exigiendo `quote` con el número, y el `quote` solo puede venir de un mensaje del usuario.

## Cambios

### 1. Request

`ChatMessage` acepta `attachments: list[str] = []` (ids, máximo 5) solo en mensajes del usuario. Con `provider`, `expected_source` y `messages` como hoy.

Al recibir la request, por cada id del **último** mensaje:

* Buscarlo con `get_attachment(id, owner)`: tiene que ser del usuario, del proyecto, `ready` y no vencido. Si no, 422.
* `image`: descargar y armar un bloque de imagen (IA-1). El mensaje del usuario pasa a ser `[imagen..., {"type": "text", "text": ...}]`.
* `log`: no se descarga. Se agrega al texto una línea `[Adjunto de log: <filename>, id <id>, <bytes> bytes]`.

Las imágenes de mensajes anteriores no se reenvían: se reemplazan por `[Imagen adjunta antes: <filename>]`. Así el historial no crece con cada turno.

Los adjuntos requieren sesión. Sin usuario y con `attachments` no vacío: 401.

### 2. Tools nuevas en `AgentTools`

`AgentTools` recibe un `AttachmentStorage` opcional. Sin él, estas tools no se publican (el modo MCP queda igual).

| Tool | Argumentos | Devuelve |
|---|---|---|
| `list_attachments` | `project_id` | adjuntos vigentes con `id`, `kind`, `filename`, `bytes` |
| `read_log` | `project_id`, `attachment_id`, `start=1`, `lines=200` | líneas numeradas, máximo 400, cortadas a 500 caracteres |
| `grep_log` | `project_id`, `attachment_id`, `pattern` | hasta 100 coincidencias con número de línea |
| `analyze_log` | `project_id`, `attachment_id` | resumen determinista (abajo) |
| `apply_log_traffic` | `project_id`, `version`, `attachment_id` | versión nueva con el tráfico observado |

### 3. `analyze_log` (módulo `backend/app/agent/logs.py`, sin LLM)

Detecta el formato línea a línea y acepta: access log de nginx o Apache (combinado), líneas de uvicorn o gunicorn, y JSON por línea con campos de método, ruta, estado y duración (probar nombres comunes: `method`, `path`/`url`/`uri`, `status`/`status_code`, `duration_ms`/`latency`/`request_time`, `time`/`timestamp`/`@timestamp`).

Devuelve:

```json
{
  "format": "nginx_combined", "lines": 48210, "parsed": 47990, "unparsed_sample": ["..."],
  "window": {"from": "...", "to": "...", "seconds": 3600},
  "peak_rps": {"value": 41.2, "unit": "req/s", "label": "OBSERVADO", "source": "log access.log: máximo en ventanas de 60 s"},
  "mean_rps": {...},
  "error_rate": {...},
  "latency_p95_ms": {...},
  "endpoints": [{"id": "GET /articles/{id}", "requests": 9120, "weight": 0.19, "p95_ms": 84.0}],
  "unmatched_paths": [{"path": "/metrics", "requests": 3600}]
}
```

* `latency_p95_ms` y los `p95_ms` solo si el log trae duración. Si no, se omiten: no se estiman.
* Las rutas se normalizan contra los endpoints del modelo (`/articles/123` calza con `/articles/{id}`). Lo que no calza va a `unmatched_paths`.
* Si menos del 50 % de las líneas se pudo interpretar: `{"error": "No reconocí el formato..."}` con tres líneas de muestra, para que el modelo use `read_log` y le pregunte al usuario.
* Leer en streaming por líneas: no cargar 10 MB como una lista de dicts.

### 4. `apply_log_traffic`

Vuelve a correr `analyze_log` (no confía en números que le pase el modelo) y crea una versión con:

* `traffic.peak_rps` desde `peak_rps`, `OBSERVADO`.
* `endpoints[].weight` desde `weight` para los endpoints que calzaron, `OBSERVADO`. Los que no aparecen en el log conservan su peso y los pesos se renormalizan a 1.
* Nota de la versión: "Tráfico observado en `<archivo>`".

Mirar cómo `set_traffic` crea la versión y recalcula escenarios, y reutilizarlo.

### 5. Insistir

Dos mecanismos, porque el prompt solo no basta:

* **Prompt.** Agregar a `INSTRUCTIONS` un párrafo: si la versión tiene supuestos con `needs_review` sobre tráfico, pesos de endpoints o latencias, pide un log de acceso o una captura de sus métricas antes de dar una conclusión, di qué número respaldaría y vuelve a pedirlo al final de cada respuesta mientras falte. Si el usuario dice que no tiene, deja de pedir y avisa que el resultado se apoya en supuestos.
* **Dato del backend.** El evento `done` agrega `evidence`:

  ```json
  {"pending": [{"field": "traffic.peak_rps", "ask": "log de acceso o captura de requests por segundo", "accepts": ["log", "image"]}], "total_assumptions": 39}
  ```

  Se calcula sin LLM, a partir de los `needs_review` de la última versión del proyecto, agrupados en a lo más cuatro pedidos: tráfico pico, pesos de endpoints, latencia de servicios externos y tasa de aciertos de caché. Función `pending_evidence(model) -> list[dict]` en `app/agent/tools.py` o junto a `collect_assumptions`.

## Criterios de aceptación

Con el LLM falso y `InMemoryAttachmentStorage`:

* Un mensaje con una imagen llega al LLM como bloque de imagen seguido de texto. En el turno siguiente, esa imagen ya no va.
* Un adjunto de otro usuario, vencido o `pending`: 422.
* `analyze_log` sobre un fixture nginx de unas 200 líneas (`tests/fixtures/access.log`, generado en el test o versionado): `peak_rps`, pesos y tasa de error exactos y conocidos de antemano.
* `analyze_log` sobre JSON por línea con duración: trae `latency_p95_ms`. Sin duración: no lo trae.
* `analyze_log` sobre texto libre: error con muestra.
* `apply_log_traffic` crea una versión cuyos `peak_rps` y `weight` tienen `label == "OBSERVADO"` y cuyos pesos suman 1.
* `set_traffic` sigue rechazando un número que no esté en `quote` (test existente).
* `done.evidence.pending` trae el pedido de tráfico en un proyecto recién ingerido y deja de traerlo después de `apply_log_traffic`.
* Sin `AttachmentStorage`, `AgentTools.schemas()` es igual a hoy (el test de MCP no cambia).

## Fuera de alcance

* Guardar el historial en `chat_sessions`.
* Calibrar latencias de pasos del modelo con el p95 del log. Se muestra, no se aplica.
* Trazas, métricas de Prometheus y PDF.
