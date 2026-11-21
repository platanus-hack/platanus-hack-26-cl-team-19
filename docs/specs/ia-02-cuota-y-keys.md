# IA-2: Cuota de la key de Branchpoint para chat y extracción

**Área:** backend, DB · **Depende de:** nada · **Tamaño:** S · **Bloquea:** IA-5

## Objetivo

La key de Branchpoint es para demostrar el producto. Hoy limita 30 mensajes de chat al día por usuario. Falta que cubra la extracción, que tenga un tope de gasto por turno y que OpenAI pueda tener key de Branchpoint.

## Leer antes

* `backend/app/api/routes/credentials.py`: `chat_key`, `team_key`, `TEAM_CHAT_LIMIT`.
* `backend/app/db/postgres_store.py`: `charge_team_chat`, `team_chat_used`.
* `supabase/migrations/20261121161000_chat_quota.sql`: tabla `team_chat_usage`.

## Cambios

### 1. Cuota por propósito

* Migración nueva en `supabase/migrations/`: agregar a `team_chat_usage` la columna `extractions integer not null default 0` y cambiar el check de `messages` a `>= 0` (una fila puede existir solo por una extracción). Replicar el cambio en `backend/app/db/schema.sql` si la tabla está ahí.
* Store: `charge_team(owner, purpose, limit) -> bool` y `team_used(owner) -> dict` con `messages` y `extractions`. La suma tiene que ser atómica, como el `insert ... on conflict ... where` de hoy.
* Límites por variable de entorno, con estos valores por defecto: `BRANCHPOINT_TEAM_CHAT_LIMIT=30`, `BRANCHPOINT_TEAM_EXTRACT_LIMIT=2`.

### 2. Una sola función para elegir la key

Renombrar `chat_key` a `llm_key(request, user, provider, override, expected_source, purpose="chat") -> LlmKey`, con `LlmKey(key: str, source: "header" | "personal" | "team")`.

El orden no cambia: key del header, key personal guardada, key de Branchpoint con cuota. `source` sirve para aplicar el tope del punto 3 solo a `team`.

Si se acaba la cuota de extracción, error 429 con código `team_extract_quota` y un mensaje que invite a guardar una key propia.

### 3. Tope de gasto por turno con la key de Branchpoint

Un mensaje puede dar 8 vueltas y una extracción 40. Con `source == "team"`:

* Chat: `max_iterations=8` (igual que hoy).
* Extracción: cortar el loop si los tokens acumulados de entrada más salida pasan `BRANCHPOINT_TEAM_EXTRACT_TOKENS` (por defecto 1.500.000). El corte termina con `stop_reason="budget"`.

Implementarlo como parámetro `max_tokens_total: int | None` de `run_agent` (coordinar con IA-1 si se hacen en paralelo: es un parámetro independiente).

Con key personal o del header no hay tope nuestro.

### 4. Key de OpenAI de Branchpoint (opcional)

`team_key("openai")` lee `OPENAI_API_KEY`. Si no está, se comporta como hoy. Quitar el rechazo fijo de `select_chat_key` para OpenAI con `source="team"` y reemplazarlo por "no hay key de Branchpoint para ese proveedor".

### 5. `GET /credentials/chat-settings`

Agregar a la respuesta, sin quitar campos:

```json
{"extract": {"remaining": 2, "limit": 2}}
```

## Criterios de aceptación

* Test: dos extracciones con la key de Branchpoint pasan y la tercera del mismo día responde 429 `team_extract_quota`.
* Test: la cuota de chat y la de extracción son independientes.
* Test: con key personal seleccionada no se descuenta cuota.
* Test: `run_agent` con `max_tokens_total` corta con `stop_reason="budget"` cuando el LLM falso reporta más tokens que el tope.
* Test: sin `OPENAI_API_KEY`, OpenAI con la key de Branchpoint responde 422 como hoy.
* Los tests existentes de credenciales y chat pasan.

## Fuera de alcance

* Cuota por dólares. El costo se muestra (`cost_usd`), pero la cuota cuenta usos y tokens.
* Cobrar o planes pagados.
