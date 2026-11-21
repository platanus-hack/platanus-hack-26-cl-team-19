# IA-1: Capa LLM: imágenes y modelos configurables

**Área:** backend · **Depende de:** nada · **Tamaño:** S · **Bloquea:** IA-7

## Objetivo

Que los dos adaptadores acepten imágenes y que el modelo de cada proveedor se elija por configuración, por separado para el chat y para la extracción.

## Leer antes

* `backend/app/agent/loop.py`: `LLM`, `Turn`, `AnthropicLLM`, `run_agent`.
* `backend/app/agent/openai_llm.py`: `OpenAILLM`, `response_input`.
* `backend/tests/agent/test_loop.py`: el LLM falso de los tests.
* La PR #59 también toca `loop.py`: si no está mergeada, coordinar para no chocar.

## Cambios

### 1. Imágenes en el historial

El historial interno usa bloques con la forma de Anthropic. Agregar el bloque de imagen en mensajes del usuario:

```json
{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "<base64>"}}
```

* `AnthropicLLM`: no cambia, la API acepta ese bloque.
* `OpenAILLM.response_input`: hoy descarta todo bloque del usuario que no sea `tool_result`. Tiene que convertir un mensaje de usuario con lista de bloques en un item `{"role": "user", "content": [...]}` donde `text` pasa a `{"type": "input_text", "text": ...}` e `image` pasa a `{"type": "input_image", "image_url": "data:<media_type>;base64,<data>"}`. Verificar los nombres contra la documentación de la Responses API antes de escribirlo.
* Tipos aceptados: `image/png`, `image/jpeg`, `image/webp`, `image/gif`.

### 2. Modelo por proveedor y por propósito

* Nueva función `model_for(provider, purpose)` con `purpose` en `chat` o `extract`. Lee `BRANCHPOINT_<PROVIDER>_<PURPOSE>_MODEL` (por ejemplo `BRANCHPOINT_ANTHROPIC_EXTRACT_MODEL`) y, si no está, usa el valor de hoy: `claude-opus-5-5` y `gpt-4.1-mini`.
* `OpenAILLM.__init__(api_key, model=None)`: hoy el modelo es un atributo de clase.
* Documentar las variables en `backend/.env.example`.
* Si el modelo no está en `llm_tokens.usd_per_million` de `app/costs/prices/manual.json`, `cost_usd` ya devuelve `None`. No inventar precios: agregar la fila solo con una fuente.

## Criterios de aceptación

* Test de `model_for`: sin variables devuelve los modelos de hoy; con `BRANCHPOINT_OPENAI_EXTRACT_MODEL` devuelve ese valor solo para OpenAI y `extract`.
* Test de `response_input` con un mensaje de usuario con texto e imagen: produce un solo item con `input_text` e `input_image`.
* Test: un mensaje de usuario que es solo texto (string) sigue funcionando igual en los dos adaptadores.
* `POST /projects/{id}/chat` se comporta igual que antes (los tests de `tests/api` pasan sin cambios de contrato).
* `ruff check` y `ruff format --check` limpios.

## Fuera de alcance

* Streaming token a token.
* Aceptar adjuntos en la API del chat: es IA-7.
