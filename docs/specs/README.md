# IA en Branchpoint: evaluación y specs

Evaluación de dos funcionalidades de IA y el plan para construirlas. Fecha: 2026-11-21. Rama: `dvillasc/docs/specs-ia-extraccion-y-chat`.

1. **Extracción con IA**: sacar la infraestructura de uno o más repos, sin depender de la tecnología.
2. **Chatbot con evidencia**: preguntar por la infraestructura, evaluar agregar o quitar componentes, y subir imágenes o logs del sistema real. El chat insiste en pedirlos.

Y dos formas de pagar la IA: la key de Branchpoint, con cuota, y la key del usuario, sin tope nuestro. Proveedores: Anthropic y OpenAI.

## Decisión sobre la extracción

**El agente se encarga de toda la extracción.** No hay extractor por AST ni camino híbrido: un agente lee el repo con tools de solo lectura y entrega la arquitectura, para cualquier framework, FastAPI incluido.

Es la decisión del ADR 0002 de la [PR #59](https://github.com/platanus-hack/platanus-hack-26-cl-team-19/pull/59) (`docs/adr/0002-la-ia-lee-la-arquitectura-del-repo.md`), que ya la implementa. Las specs de extracción de esta carpeta **parten de esa PR** y cubren lo que le falta. No agregan otro ADR.

Lo que ya trae la PR #59:

| Pieza | Dónde |
|---|---|
| Agente que lee el tarball: `list_files`, `read_file`, `grep`, `submit_architecture`, tope de 40 vueltas | `backend/app/ingest/analyzer.py` |
| Schema estricto de la propuesta, sin campos de tiempo ni costo | `backend/app/ingest/ai_graph.py` (`ArchitectureSubmission`) |
| Modelo armado con el catálogo; workers y pool verificados contra la línea citada | `build_from_ai`, `build_from_graph` |
| La misma tool por MCP, para la CLI del usuario | `backend/app/agent/mcp.py` |
| Extractor AST borrado | `backend/app/ingest/extract.py` |

Lo que le falta, y cubren estas specs:

| Falta | Spec |
|---|---|
| Tiene conflictos con `dev` y su credencial (modo demo en `llm_access.py`) no es la cuota que ya está en `dev` (PR #62) | IA-2, IA-3 |
| Solo Anthropic en la ingesta, y el frontend no manda credencial: en producción la importación responde 422 | IA-3 |
| El analizador del servidor no se ha probado con un LLM real | IA-0 |
| La evidencia de endpoints y pasos no se verifica contra los archivos; no hay tope de tokens ni progreso | IA-4 |
| Un solo repo por proyecto | IA-5, IA-10 |

## Veredicto

| Parte | ¿Factible? | Por qué |
|---|---|---|
| Capa de proveedores (Anthropic y OpenAI) | Sí, ya existe | `app/agent/loop.py` define la interfaz `LLM`, con `AnthropicLLM` y `OpenAILLM` (80 líneas). Faltan imágenes y modelos configurables. |
| Key de Branchpoint con cuota y key del usuario | Sí, ya existe para el chat | `app/api/routes/credentials.py`: 30 mensajes al día con la key del equipo, keys personales en Supabase Vault. Falta cubrir la extracción. |
| Chat con imágenes y logs | Sí | Es trabajo conocido: Supabase Storage, bloques de imagen en los dos proveedores y tools nuevas. |
| Chat que agrega y quita componentes | Sí, acotado | Cada cambio es una operación tipada nueva en `app/agent/ops.py`. Solo se puede simular lo que el motor modela. |
| Extracción hecha por el agente | Construida en la PR #59, **calidad sin medir** | Hay una prueba por CLI sobre un repo Express (19 endpoints). No sabemos cuánto encuentra, cuesta ni demora el analizador del servidor en repos reales. Lo mide [IA-0](ia-00-medir-analizador.md). |
| Varios repos en un proyecto | Diagrama sí, simulación parcial | El motor simula una API, una DB, caché y colas. Con varios servicios se simula uno y el resto queda como dependencia externa. |

Al no haber AST, ya no hay respaldo: si el agente falla o no hay credencial, el repo no se importa. Eso hace de IA-0 e IA-3 lo primero.

## Cómo se ve en código

No hace falta LangChain. El repo ya tiene las piezas de un harness propio, y son pequeñas:

```
LLM (Protocol)            complete(system, messages, tools) -> Turn      app/agent/loop.py
  AnthropicLLM            SDK anthropic, Messages API
  OpenAILLM               SDK openai, Responses API                      app/agent/openai_llm.py
run_agent(...)            loop del chat: modelo -> tool calls -> resultados
AgentTools                tools del chat con Pydantic                    app/agent/tools.py
analyze_repo(...)         loop de la extracción, con RepoReader          app/ingest/analyzer.py (PR #59)
```

Las dos funcionalidades son el mismo patrón con otro juego de tools: el modelo pide una tool, el backend valida los argumentos con Pydantic, la ejecuta y devuelve el resultado. Las tools "locales" son funciones Python del backend.

**Por qué no LangChain ni LiteLLM.** Son dos proveedores y el adaptador de cada uno cabe en una pantalla. Una capa genérica esconde lo que cada API pide de vuelta en una conversación con tools (los bloques de thinking de Anthropic, los items de salida de la Responses API) y eso el repo ya lo resuelve. Como `analyze_repo` recibe cualquier `LLM`, soportar OpenAI en la extracción es pasarle `OpenAILLM`.

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
| IA-0 | [Medir el analizador con LLM reales](ia-00-medir-analizador.md) | backend | rama de la PR #59 | S |
| IA-1 | [Capa LLM: imágenes y modelos configurables](ia-01-capa-llm.md) | backend | — | S |
| IA-2 | [Cuota de la key de Branchpoint](ia-02-cuota-y-keys.md) | backend, DB | — | S |
| IA-6 | [Adjuntos en Supabase Storage](ia-06-adjuntos-storage.md) | backend, DB | — | M |
| IA-8 | [Operaciones para agregar y quitar componentes](ia-08-ops-agregar-quitar.md) | backend | — | M |
| IA-3 | [Llevar el analizador a `dev` con la credencial unificada](ia-03-analizador-en-dev.md) | backend, frontend | PR #59, IA-2 | M |
| IA-7 | [Chat con adjuntos y evidencia](ia-07-chat-evidencia.md) | backend | IA-1, IA-6 | M |
| IA-9 | [Frontend: adjuntos y tarjeta de evidencia](ia-09-frontend-chat.md) | frontend | contrato de IA-6 e IA-7 | M |
| IA-4 | [Analizador: evidencia verificada, presupuesto y progreso](ia-04-analizador-robustez.md) | backend | IA-3, resultado de IA-0 | M |
| IA-5 | [Varios repos por proyecto](ia-05-ingesta-multirepo.md) | backend, DB | IA-3 | L |
| IA-10 | [Frontend: varios repos en el proyecto y el diagrama](ia-10-frontend-multirepo.md) | frontend | contrato de IA-5 | M |

```
Ola 1 (paralelo):  IA-0   IA-1   IA-2   IA-6   IA-8
Ola 2:             IA-3 (#59, 2)        IA-7 (1,6)     IA-9 (contratos)
Ola 3:             IA-4 (3, 0)          IA-5 (3)       IA-10 (contrato de 5)
```

Reparto sugerido para cuatro personas: quien lleva la PR #59 sigue con la extracción (IA-3, IA-4, IA-5), otra persona el chat de backend (IA-1, IA-6, IA-7), otra el frontend (IA-9, IA-10) y otra medición, cuota y operaciones (IA-0, IA-2, IA-8).

## Decisiones que tiene que tomar el equipo

1. **Umbral de IA-0.** Se propone: al menos 80 % de los endpoints, ninguno inventado, menos de 3 minutos y menos de US$ 1 por repo. Si no se cumple, se ajusta el prompt y los límites (IA-4) antes de abrir la importación al público. No hay camino alternativo.
2. **Cuota de extracción con la key de Branchpoint.** IA-2 propone 5 repos analizados al día por usuario, el mismo número del modo demo de la PR #59.
3. **Key de OpenAI de Branchpoint.** Hoy la key del equipo es solo de Anthropic. IA-2 la deja opcional con `OPENAI_API_KEY`.
4. **Login en producción.** Producción corre con `BRANCHPOINT_AUTH=off`. La cuota y los adjuntos necesitan un usuario: sin login solo funciona la key en el header y no hay adjuntos.

## Fuera de alcance

* Simular varios servicios a la vez. Es un cambio del motor (`app/engine`).
* Guardar el historial del chat en `chat_sessions`. Las tablas existen y nadie las usa.
* Otros proveedores (Gemini, modelos locales).
* El modo MCP: `submit_architecture` ya existe ahí. Las tools de adjuntos dependen de una sesión del editor y no se publican por MCP.
