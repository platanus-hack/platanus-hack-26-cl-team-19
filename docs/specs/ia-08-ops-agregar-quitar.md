# IA-8: Operaciones para agregar y quitar componentes

**Área:** backend · **Depende de:** nada · **Tamaño:** M

## Objetivo

Que el agente pueda evaluar "¿y si quito X?" además de "¿y si agrego X?". Hoy `propose_version` solo agrega o escala.

## Leer antes

* `backend/app/agent/ops.py` completo: es el patrón a seguir.
* `backend/tests/agent/test_ops.py`.
* `backend/app/models/architecture.py`: qué entiende el motor (`on_miss`, colas, pooler).
* `backend/app/catalog/catalog.json`.

## Regla

Una operación existe solo si el motor puede simular su efecto. Las operaciones son un conjunto cerrado: agregar una es código, no prompt (ADR 0001).

## Operaciones nuevas

| Op | Argumentos | Efecto en el modelo | Inversa de |
|---|---|---|---|
| `remove_cache` | `endpoint` | El paso de caché desaparece y el paso que estaba en `on_miss` vuelve a ejecutarse siempre. Quita el costo de la caché si ningún endpoint la usa. | `add_cache` |
| `remove_pooler` | — | Vuelve a los límites de conexiones del plan de DB sin pooler. Quita su costo. | `add_pooler` |
| `move_to_sync` | `endpoint`, `step` | El paso encolado vuelve al request. Si la cola queda sin tareas, se quita con sus workers y su costo. | `move_to_queue` |
| `scale_workers` | `queue`, `workers`, `quote?` | Cambia los workers de una cola existente. | — |

Para cada una:

* Clase Pydantic con `op: Literal[...]`, `extra="forbid"` y descripciones en español, agregada a la unión `Op`.
* Función `_<op>(m, op, catalog, warnings) -> str` que devuelve la frase del cambio.
* Errores como `OpError` con un mensaje que diga qué valores sí existen. Ejemplos: "El endpoint 'GET /x' no tiene caché. Tienen caché: ...", "El proyecto no tiene pooler."
* Los números que aparecen (límites de conexiones al quitar el pooler) salen del catálogo o del plan actual, con su etiqueta.
* `apply_ops` ya verifica que el resultado cargue en el motor: no saltarse ese paso.

Antes de implementar `remove_cache` y `move_to_sync`, mirar qué guardan hoy `_add_cache` y `_move_to_queue`. La inversa tiene que funcionar también sobre cachés y colas que venían del repo, no solo sobre las que agregó el agente. Si el modelo no guarda lo necesario para revertir (por ejemplo, el tiempo original del paso), el caso se rechaza con un `OpError` claro en vez de adivinar.

## Lo que no se puede simular

Si el usuario pide algo que ninguna op cubre (réplica de lectura, CDN, cambiar de base de datos, partir un servicio), el agente tiene que decirlo. Agregar a `INSTRUCTIONS` en `app/agent/mcp.py`: "Si el cambio que piden no está en `ops_schema`, di que Branchpoint todavía no lo simula. No lo aproximes con otra operación sin avisar."

## Criterios de aceptación

* Ida y vuelta: `add_cache` y luego `remove_cache` sobre el fixture deja los pasos del endpoint y el costo iguales al original. Lo mismo para `add_pooler` con `remove_pooler` y `move_to_queue` con `move_to_sync`.
* Cada op nueva tiene su test de error: endpoint sin caché, proyecto sin pooler, paso que no está en una cola, cola inexistente.
* `scale_workers` con `quote` deja la fuente del usuario, y sin `quote` queda `SUPUESTO` con "Propuesta del agente", igual que `scale_api`.
* `ops_json_schema()` incluye las cuatro ops.
* Tras cada op, `load_model` acepta el modelo y `simulate` corre.
* Los tests existentes de `test_ops.py` y `test_tools.py` pasan.

## Fuera de alcance

* Réplicas de lectura, CDN, sharding y cualquier op que necesite cambios en `app/engine`.
* UI: `AgentProposalCard.vue` y `ChangeDiff.vue` ya muestran versiones propuestas. Comprobar a mano que las ops nuevas se ven bien y, si no, abrir una issue.
