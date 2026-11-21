# IA-3: Llevar el analizador a `dev` con la credencial unificada

**Área:** backend, frontend · **Depende de:** PR #59, IA-2 · **Tamaño:** M · **Bloquea:** IA-4, IA-5

## Objetivo

Que la importación desde GitHub funcione en `dev` y en producción con el agente como único extractor: la PR #59 integrada, una sola regla de credenciales para chat y extracción, los dos proveedores y el frontend mandando lo necesario.

Lo ideal es hacerlo sobre la rama de la PR #59, con quien la lleva. Si esa PR se mergea antes, esta spec es la PR siguiente.

## Leer antes

* La PR #59 completa, en especial `backend/app/ingest/analyzer.py`, `backend/app/api/llm_access.py`, `backend/app/api/routes/github.py` (`start_ingestion`) y `backend/app/github/ingestion.py`.
* `docs/adr/0002-la-ia-lee-la-arquitectura-del-repo.md` (en esa PR).
* `backend/app/api/routes/credentials.py` en `dev`: la cuota y las keys de la PR #62. Con IA-2, `llm_key(..., purpose)`.
* `frontend/app/services/github-api.ts` y `frontend/app/composables/useGithubConnection.ts`.

## Problema

* La PR #59 tiene conflictos con `dev` en `backend/app/agent/tools.py`, `backend/app/api/routes/chat.py` y `docs/despliegue.md`.
* Hay dos reglas de credenciales. La PR #59 usa `llm_access.resolve_llm`: key en el header o modo demo con `BRANCHPOINT_CHAT_DEMO=on` y un tope en memoria. `dev` usa `credentials.chat_key`: key en el header, key personal guardada en Vault o key del equipo con cuota en Postgres.
* La ingesta solo acepta Anthropic.
* El frontend no manda credencial ni proveedor al importar: en producción la importación responde 422.

## Cambios

### 1. Resolver los conflictos

Al mezclar, se conserva lo de `dev` para credenciales y cuota (`credentials.py`, `expected_source`, los dos proveedores en el chat) y lo de la PR #59 para `submit_architecture` y el resto.

### 2. Una sola regla de credenciales

* Borrar `backend/app/api/llm_access.py` y la variable `BRANCHPOINT_CHAT_DEMO` (código, `.env.example`, `docs/despliegue.md`, ADR 0002).
* `start_ingestion` resuelve la credencial con `llm_key(request, user, provider, header, None, purpose="extract")` de IA-2. Orden: key del header, key personal guardada, key de Branchpoint con cuota.
* El 422 sin credencial y el 429 `team_extract_quota` salen en la respuesta de `POST /github/ingestions`, antes de encolar.
* La key no se guarda en `Ingestion` ni se escribe en logs. Mantener el test de la PR #59 que lo comprueba.

### 3. Proveedor en la ingesta

* `StartIngestion` gana `provider: Literal["anthropic", "openai"] = "anthropic"`.
* Headers `X-Anthropic-Api-Key` y `X-OpenAI-Api-Key`, como en el chat.
* El `LLM` se arma con la fábrica del proveedor (`app.state.llm_factory` o `app.state.openai_llm_factory`) y el modelo de `model_for(provider, "extract")` si IA-1 ya está; si no, el modelo por defecto.
* `repo.source.analysis` guarda también `provider`.
* `analyzer.py` no cambia: ya recibe cualquier `LLM`. Revisar solo que `OpenAILLM` acepte el primer mensaje del usuario como string y los `tool_result` que arma `analyze_repo`.

### 4. Frontend

En `github-api.ts`, `useGithubConnection.ts` y `NewProjectSheet.vue`:

* Mandar `provider` en el cuerpo. El selector de proveedor usa el mismo criterio que el chat (`useApiCredentials.ts`).
* Mostrar bajo el botón qué credencial se usará: "Usarás tu API key de Anthropic" o "Te quedan N de M análisis con la key de Branchpoint hoy", con `extract.remaining` de `GET /credentials/chat-settings` (IA-2).
* Con 422 o 429: mostrar `error.message` del backend y un enlace a Configuración. No reintentar solo.
* Quitar de la UI cualquier texto que diga que Branchpoint analiza apps FastAPI.

### 5. Documentación

* ADR 0002: en "Consecuencias", reemplazar el modo demo por la cuota de IA-2 y decir que la ingesta acepta Anthropic y OpenAI.
* `docs/despliegue.md`: las variables de Render que hacen falta (`ANTHROPIC_API_KEY`, opcional `OPENAI_API_KEY`, los límites de IA-2).

## Criterios de aceptación

* `git merge origin/dev` sin conflictos y `pytest` completo en verde.
* Test: `POST /github/ingestions` con `provider="openai"` y key en el header usa la fábrica de OpenAI (un LLM falso registrado en `app.state.openai_llm_factory`) y termina `done`.
* Test: sin header y con key personal guardada, usa la personal y no descuenta cuota.
* Test: sin header ni key personal, usa la de Branchpoint y descuenta 1. Pasado el límite: 429 `team_extract_quota`.
* Test: sin ninguna credencial disponible: 422 con el mensaje que sugiere guardar una key o usar la CLI por MCP.
* No queda ninguna referencia a `BRANCHPOINT_CHAT_DEMO` ni a `llm_access` (`grep` vacío).
* A mano, en local con una key real: importar un repo que no sea FastAPI desde la web, de punta a punta. Captura en la PR.
* `npm run typecheck` y el lint del frontend pasan.

## Fuera de alcance

* Varios repos: IA-5.
* Verificar evidencia, tope de tokens y progreso: IA-4.
