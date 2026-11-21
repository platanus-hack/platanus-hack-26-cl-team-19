# IA en Branchpoint: evaluación y specs

Evaluación de dos funcionalidades de IA y el plan para construirlas. Fecha: 2026-11-21. Rama: `dvillasc/docs/specs-ia-extraccion-y-chat`.

1. **Extracción con IA**: sacar la infraestructura de uno o más repos, sin depender de la tecnología.
2. **Chatbot con evidencia**: preguntar por la infraestructura, evaluar agregar o quitar componentes, y subir imágenes o logs del sistema real. El chat insiste en pedirlos.

Y dos formas de pagar la IA: la key de Branchpoint, con cuota, y la key del usuario, sin tope nuestro. Proveedores: Anthropic y OpenAI.

## Veredicto

| Parte | ¿Factible? | Por qué |
|---|---|---|
| Capa de proveedores (Anthropic y OpenAI) | Sí, ya existe | `app/agent/loop.py` define la interfaz `LLM`, con `AnthropicLLM` y `OpenAILLM` (80 líneas). Faltan imágenes y modelos configurables. |
| Key de Branchpoint con cuota y key del usuario | Sí, ya existe para el chat | `app/api/routes/credentials.py`: 30 mensajes al día con la key del equipo, keys personales en Supabase Vault. Falta cubrir la extracción y poner un tope de tokens. |
| Chat con imágenes y logs | Sí | Es trabajo conocido: Supabase Storage, bloques de imagen en los dos proveedores y tools nuevas. |
| Chat que agrega y quita componentes | Sí, acotado | Cada cambio es una operación tipada nueva en `app/agent/ops.py`. Solo se puede simular lo que el motor modela. |
| Extracción con IA, agnóstica | Factible de construir, **calidad sin medir** | El loop y las tools son simples. No sabemos cuántos endpoints encuentra, cuánto cuesta ni cuánto demora en un repo real. Por eso parte con un spike ([IA-0](ia-00-spike-extractor.md)). |
| Varios repos en un proyecto | Diagrama sí, simulación parcial | El motor simula una API, una DB, caché y colas. Con varios servicios se simula uno y el resto queda como dependencia externa. |

## Cómo se ve en código

No hace falta LangChain. El repo ya tiene las tres piezas de un harness propio, y son pequeñas:

```
LLM (Protocol)            complete(system, messages, tools) -> Turn      app/agent/loop.py
  AnthropicLLM            SDK anthropic, Messages API
  OpenAILLM               SDK openai, Responses API                      app/agent/openai_llm.py
run_agent(...)            loop: modelo -> tool calls -> resultados       app/agent/loop.py
AgentTools                tools con Pydantic, schemas() y call()         app/agent/tools.py
```

Las dos funcionalidades son el mismo loop con otro juego de tools:

```
                     ┌── RepoTools (list_dir, read_file, grep, submit_graph)   -> extracción
run_agent(tools, llm)┤
                     └── AgentTools (+ adjuntos, + ops nuevas)                 -> chat
```

Las tools "locales" son funciones Python del backend. El modelo pide una, el backend valida los argumentos con Pydantic, la ejecuta y devuelve el resultado. Así funciona hoy el chat.

**Por qué no LangChain ni LiteLLM.** Son dos proveedores y el adaptador de cada uno cabe en una pantalla. Una capa genérica esconde lo que cada API pide de vuelta en una conversación con tools (los bloques de thinking de Anthropic, los items de salida de la Responses API) y eso el repo ya lo resuelve. Agregar un tercer proveedor es escribir otra clase con `complete`.

### Extracción: tres opciones

| Opción | Cómo | Problema |
|---|---|---|
| A. Un solo prompt con el repo entero | Empaquetar los archivos y pedir JSON | El tarball admite hasta 80 MB. Un repo mediano no cabe o cuesta mucho, y no hay cómo verificar lo que devuelve. |
| B. Agente con tools sobre el repo extraído | `list_dir`, `read_file`, `grep` y un `submit_graph` final | Más vueltas, pero lee solo lo que necesita y se puede validar. |
| **C. Híbrido (recomendada)** | Lo determinista primero (`iac.py` para todos; `extract.py` si es FastAPI) y el agente de B completa el resto | La más barata y la que mejor conserva lo que ya funciona. |

Con C, el LLM entrega **estructura con evidencia** (`archivo:línea`), no números. El backend verifica que cada archivo y línea existan y arma el modelo con el catálogo, como hoy. La regla "el LLM nunca inventa números" de ADR 0001 se mantiene. Lo que cambia es que ahora el LLM sí extrae la estructura, que ADR 0001 había descartado: por eso hay un [ADR 0002](../adr/0002-extraccion-con-llm-para-repos-no-fastapi.md).

### Chat: qué falta

Hoy el chat solo acepta texto y el historial vive en el navegador. Para los adjuntos:

* Los archivos van a un bucket privado de Supabase Storage, con vencimiento.
* Las imágenes se le pasan al modelo como bloques de imagen.
* Los logs **no** se le pasan enteros. Una tool determinista los resume (pico de req/s, peso de cada endpoint, p95) y esos números quedan `OBSERVADO`. El modelo puede leer tramos con otra tool.
* "Insistir" no depende solo del prompt: el backend calcula qué supuestos siguen sin respaldo y lo manda en el evento `done`. El frontend muestra la tarjeta para subir evidencia.

## Specs

Cada spec es una PR. Las de la ola 1 no dependen entre sí.

| ID | Spec | Área | Depende de | Tamaño |
|---|---|---|---|---|
| IA-0 | [Spike del extractor](ia-00-spike-extractor.md) | backend | — | S |
| IA-1 | [Capa LLM: imágenes, modelos y loop genérico](ia-01-capa-llm.md) | backend | — | S |
| IA-2 | [Cuota de la key de Branchpoint](ia-02-cuota-y-keys.md) | backend, DB | — | S |
| IA-3 | [Contrato `graph/v1` y validador](ia-03-grafo-v1.md) | backend | — | M |
| IA-6 | [Adjuntos en Supabase Storage](ia-06-adjuntos-storage.md) | backend, DB | — | M |
| IA-8 | [Operaciones para agregar y quitar componentes](ia-08-ops-agregar-quitar.md) | backend | — | M |
| IA-4 | [Extractor agente](ia-04-extractor-agente.md) | backend | IA-0, IA-1, IA-3 | M |
| IA-5 | [Ingesta con IA y varios repos](ia-05-ingesta-multirepo.md) | backend, DB | IA-2, IA-3, IA-4 | L |
| IA-7 | [Chat con adjuntos y evidencia](ia-07-chat-evidencia.md) | backend | IA-1, IA-6 | M |
| IA-9 | [Frontend: adjuntos y tarjeta de evidencia](ia-09-frontend-chat.md) | frontend | contrato de IA-6 e IA-7 | M |
| IA-10 | [Frontend: varios repos y diagrama de componentes](ia-10-frontend-multirepo.md) | frontend | contrato de IA-3 e IA-5 | M |

```
Ola 1 (paralelo):  IA-0   IA-1   IA-2   IA-3   IA-6   IA-8
Ola 2:             IA-4 (0,1,3)         IA-7 (1,6)     IA-9 (contratos)
Ola 3:             IA-5 (2,3,4)         IA-10 (contratos)
```

Reparto sugerido para cuatro personas: una toma la extracción (IA-0, IA-3, IA-4, IA-5), otra el chat de backend (IA-1, IA-6, IA-7), otra el frontend (IA-9, IA-10) y otra cuota y operaciones (IA-2, IA-8).

## Decisiones que tiene que tomar el equipo

1. **Aceptar el ADR 0002.** Sin él, IA-4 e IA-5 contradicen el ADR 0001.
2. **Umbral del spike.** IA-0 propone: al menos 80 % de los endpoints, menos de 3 minutos y menos de US$ 1 por repo. Si no se cumple, la extracción con IA queda solo para el diagrama (componentes y conexiones), sin simular.
3. **Cuota de extracción con la key de Branchpoint.** IA-2 propone 2 al día por usuario.
4. **Key de OpenAI de Branchpoint.** Hoy la key del equipo es solo de Anthropic. IA-2 la deja opcional con `OPENAI_API_KEY`.
5. **Login en producción.** Producción corre con `BRANCHPOINT_AUTH=off`. La cuota y los adjuntos necesitan un usuario: sin login solo funciona la key en el header y no hay adjuntos.

## Fuera de alcance

* Simular varios servicios a la vez. Es un cambio del motor (`app/engine`).
* Guardar el historial del chat en `chat_sessions`. Las tablas existen y nadie las usa.
* Otros proveedores (Gemini, modelos locales).
* El modo MCP: las tools nuevas del chat quedan disponibles ahí sin trabajo extra, salvo las de adjuntos, que dependen de una sesión del editor.
