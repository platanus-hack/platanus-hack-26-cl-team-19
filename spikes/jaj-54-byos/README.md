# JAJ-54: cómo usamos la IA del usuario (Bring Your Own Subscription)

## Resultado en 5 líneas

1. **Decisión: Branchpoint es un servidor MCP. El agente corre en la CLI de IA del propio usuario**, por ejemplo Claude Code con su plan Pro/Max. El usuario conecta su CLI a Branchpoint con un comando. Desde ahí, el loop con el LLM y los tokens son suyos, y Branchpoint solo ejecuta las tools: simular, proponer y costear.
2. **Es el único camino de suscripción que permiten los proveedores.** Anthropic prohíbe que una app de terceros ofrezca el login de claude.ai o mande requests con el plan Pro/Max del usuario. Sí permite que el usuario use su propio Claude Code, sin modificar, con su suscripción. OpenAI no ofrece un "Sign in with ChatGPT" para terceros.
3. **Branchpoint no guarda ninguna credencial de IA.** En el modo CLI solo existe un token de Branchpoint para conectar la CLI al MCP (JAJ-81). El chat dentro del editor (JAJ-67) se usa solo con una API key del usuario, que no se guarda en el servidor, o con la credencial de demo del equipo, con límite de gasto.
4. **Proveedores del MVP:** Claude Code primero. Como MCP es un estándar, otras CLIs con MCP por HTTP sirven sin código extra (Gemini CLI confirmado; Codex sin verificar).
5. **Validado con Claude Code real** (plan Pro, sin API key). Conectado a `mcp_server.py`, el agente:
   * simuló CyberDay y citó el cuello de botella con su `archivo:línea`;
   * probó 4 propuestas con `propose`, porque cada arreglo movía el cuello a otro lado;
   * recomendó 6 réplicas, pooler y DB large: p95 de 22,3 s a 287 ms, 0 % de errores, +US$244/mes.

   Todos los números salieron de las tools.

## Qué permite cada proveedor

Fuentes leídas el 2026-11-21.

| Camino | Anthropic | OpenAI | Google |
|---|---|---|---|
| **Login con la suscripción del usuario dentro de nuestra app** (OAuth, rate limits del plan) | **Prohibido** sin aprobación previa ([Agent SDK](https://code.claude.com/docs/en/agent-sdk/overview), [Legal and compliance](https://code.claude.com/docs/en/legal-and-compliance)): no se puede ofrecer el login de Claude.ai ni enrutar requests con credenciales de planes Free, Pro, Max o Ultra a nombre de los usuarios. Tampoco recolectar ni intermediar sus credenciales o tokens de sesión. | No hay OAuth de ChatGPT para terceros en ninguna fuente leída. Los [Terms of Use](https://openai.com/policies/row-terms-of-use/) prohíben compartir credenciales y extraer outputs de forma automática. | Gemini CLI ya no tiene plan gratis ni Google AI Pro: pasaron a Antigravity CLI el 2026-06-18 ([gemini-cli](https://github.com/google-gemini/gemini-cli)). |
| **El usuario usa SU CLI con SU suscripción y la conecta a nuestro MCP** | **Permitido.** La política no le impide al usuario iniciar sesión con su suscripción en el binario oficial de Claude Code, sin modificar ([Legal](https://code.claude.com/docs/en/legal-and-compliance)). Remoto con `claude mcp add --transport http <name> <url>` y header `Authorization` ([MCP](https://code.claude.com/docs/en/mcp)). | Codex CLI usa "Sign in with ChatGPT" con los planes Plus/Pro. Su soporte de MCP por HTTP **no está verificado**: la doc redirige a otro sitio. | MCP por stdio, SSE y *streamable HTTP* (`httpUrl` en `settings.json`) ([MCP en Gemini CLI](https://www.geminicli.com/docs/tools/mcp-server)). |
| **Un proceso nuestro en la laptop del usuario que maneja `claude -p` para nuestra web** | **Evitar.** La doc no lo trata, pero la política pide que cada usuario se autentique con sus propias credenciales y prohíbe intermediar el uso de Claude a nombre de los usuarios ([Legal](https://code.claude.com/docs/en/legal-and-compliance)). Un relay de nuestra web encaja en "intermediar". | No consta. | No consta. |
| **El usuario nos pasa su API key** | Es el método que la doc indica a los desarrolladores: autenticación con API key de la Console o de un proveedor cloud. El uso se cobra a la cuenta dueña de la key. Que una app pida pegarla no está tratado en lo leído: no leímos los Commercial Terms. | Permitido con API key de la plataforma: es el uso normal de la API. | API key de Gemini o Vertex. |

## Decisión

### 1. Modo CLI (principal): Branchpoint como servidor MCP

```
 CLI del usuario (Claude Code, su login)          Branchpoint (backend)
 ┌──────────────────────────────┐   MCP/HTTP   ┌───────────────────────────────┐
 │ loop del agente + su LLM     │ ───────────▶ │ tools: simulate, propose,     │
 │ (tokens: plan del usuario)   │ ◀─────────── │ estimate_cost, get_model, ... │
 └──────────────────────────────┘   resultados └───────────────┬───────────────┘
                                                               │ versiones y runs
                                                               ▼
                                                  editor (ve los cambios en vivo)
```

- **Conexión (JAJ-81):** el editor muestra un comando con un token personal de Branchpoint:

  ```bash
  claude mcp add --transport http branchpoint https://<api>/mcp --header "Authorization: Bearer bp_..."
  ```

  - **El token:** identifica al usuario y al proyecto, no es una credencial de IA. Se guarda hasheado y se puede revocar.
  - **Después:** OAuth de MCP, que Claude Code soporta para servidores remotos.
  - **Conexión verificada:** el primer `tools/list` con ese token.
- **Las tools son las del ADR 0001 y salen del backend:** `simulate`, `compare`, `propose` (operaciones de JAJ-68), `estimate_cost`, `get_model`, `list_assumptions`, `set_traffic`/`set_deployment`/`set_goals` (con `quote`) y `read_file`/`grep`. Cada `propose` aceptado crea una versión con origen `agente`, y el editor la muestra.
- **"El LLM nunca inventa números" se cumple por construcción:** las tools devuelven los números del motor, el catálogo y la tabla de precios. Las `instructions` del servidor le piden al LLM citar esos resultados.

### 2. Modo chat en el editor (secundario): loop en el backend (JAJ-67)

Es para quien no tiene una CLI o para la demo. Usa el mismo conjunto de tools, ahora llamado por un loop del backend con el SDK de Anthropic.

- **Con la API key del usuario:**
  - **Dónde vive:** en el navegador (`sessionStorage`) y viaja en cada request por HTTPS.
  - **Qué hace el backend:** la usa solo para esa llamada. No la guarda, no la registra en logs y no la devuelve.
  - **Si algún día se guarda:** en Supabase Vault (`llm_credentials.secret_id` del modelo de datos de JAJ-55), nunca en claro.
- **En modo demo:** con la credencial del equipo. En el backend desplegado, mejor con Workload Identity Federation (como el bot de JAJ-63), o con una key en el secret store del hosting, más un límite de gasto mensual en la Console y un tope de mensajes por sesión.

### 3. Lo que no hacemos

- **Login de claude.ai o de ChatGPT dentro de Branchpoint:** está prohibido.
- **Guardar o recibir el token de sesión de la CLI del usuario:** está prohibido.
- **Un helper local que maneje `claude -p` para atender pedidos de la web:** se acerca a "intermediar". En modo CLI es el usuario quien conversa en su CLI, y Branchpoint solo responde tools.

## Proveedores del MVP

| Cliente | Estado | Cómo |
|---|---|---|
| Claude Code (Pro/Max o API key) | **Soportado, primero** | `claude mcp add --transport http ...` |
| Gemini CLI (Code Assist / API key) | Debería funcionar sin código extra | `httpUrl` en `~/.gemini/settings.json` |
| Codex CLI (ChatGPT o API key) | Sin verificar | Revisar si `mcp_servers` admite HTTP |
| Chat del editor | Solo con API key de Anthropic | JAJ-67 |

## Cuánto gasta cada análisis

- **Modo CLI:** el gasto lo ve el usuario en su CLI y en su plan. Branchpoint no recibe tokens ni puede medirlos, así que no muestra un número: mostrarlo sería inventarlo. Lo que sí muestra es cuántas simulaciones y propuestas pidió el agente.
- **Modo chat:** cada mensaje guarda `input_tokens`, `output_tokens` y `cost_usd`, calculado con `backend/app/costs/prices/manual.json`. Es la columna de `chat_messages` del modelo de datos de JAJ-55, y es lo mismo que hace el bot de JAJ-63 en su pie de página.

## Demo sin key del jurado

1. **Camino principal:** la laptop del equipo con Claude Code conectado al MCP de Branchpoint. Es el flujo real de producto.
2. **Respaldo:** el chat del editor en modo demo, con la credencial del equipo, límite de gasto mensual y tope de mensajes por sesión. Debe estar marcado como demo en la UI.

## Prototipo

`mcp_server.py` expone 4 tools sobre los ejemplos de `backend/app/samples`:

- `list_examples`
- `simulate`
- `ops_schema`
- `propose`

`check_client.py` es un cliente MCP por streamable HTTP, sin LLM ni credenciales.

```bash
pip install -e "./backend[dev]" mcp      # mcp 2.x (MCPServer)
python spikes/jaj-54-byos/mcp_server.py   # http://127.0.0.1:8765/mcp
python spikes/jaj-54-byos/check_client.py
```

Resultado (template en CyberDay ×20):

- **`simulate`:** p95 de 22,3 s. El cuello es la CPU de la API al 100 %, y el 59 % se va en `backend/app/core/security.py:36`, el hash de contraseñas.
- **`propose` con `scale_api` replicas 0:** devuelve `Operaciones inválidas: 0.scale_api.replicas: Input should be greater than or equal to 1`, que el LLM lee y corrige.
- **`propose` con `scale_api` replicas 4:**
  - el p95 baja de 22,3 s a 0,99 s;
  - los errores suben de 0 % a 37 %;
  - el cuello pasa a la CPU de la DB (97 %, `backend/app/api/routes/users.py:43`);
  - el costo sube de US$148,67 a US$235,17 al mes.

### Prueba con Claude Code real (2026-11-21)

Claude Code 2.1.323 con sesión **Claude Pro**, sin API key. Pregunta: "¿qué pasa en CyberDay? … propón un cambio con propose y compara".

- **Diagnóstico:**
  - la API atiende 81,1 de 262,4 req/s;
  - el p95 queda en 22,3 s;
  - el cuello es la CPU de la API al 100 %, y el 59 % se va en `backend/app/core/security.py:36`.
- **Lo que probó el agente con `propose`, en orden:**

| Cambio | p95 | Errores | Costo/mes | Nuevo cuello |
|---|---|---|---|---|
| Hoy | 22.261 ms | 0 % | US$148,67 | CPU de la API, `security.py:36` |
| 4 réplicas | 989 ms | 37,2 % | US$235,17 | CPU de la DB, `routes/users.py:43`; pide 240 conexiones y la DB acepta 60 |
| + pooler + DB small | 12.190 ms | 0 % | US$240,17 | CPU de la DB al 100 % |
| + pooler + DB large | 3.687 ms | 0 % | US$335,17 | CPU de la API al 99 % |
| **6 réplicas + pooler + DB large** | **287 ms** | **0 %** | **US$392,84** | CPU de la API al 84 % |

- **Límites que respetó:**
  - no inventó números;
  - avisó que con la CPU al 100 % el motor es optimista;
  - no simuló la caché de `GET /users/` porque la tasa de aciertos es un dato del usuario, y se la pidió;
  - señaló que `propose` no tiene una operación para abaratar el hash de contraseñas.

Para repetirlo con el servidor corriendo:

```bash
claude mcp add --transport http branchpoint http://127.0.0.1:8765/mcp
```

```bash
claude -p "Con la tool simulate de branchpoint, ¿qué pasa en CyberDay en el ejemplo full-stack-fastapi-template? Propón un cambio con propose y compáralo."
```

## Impacto en otras issues

- **JAJ-67 (loop del agente):** las tools se implementan una vez y se exponen dos veces, por MCP para el modo CLI (principal) y en el loop del backend para el modo chat. El loop del backend solo corre con la key del usuario o la de demo.
- **JAJ-81 (vincular la CLI):** emparejar es generar el token de Branchpoint y mostrar el comando `claude mcp add`. La conexión queda verificada con el primer `tools/list` con ese token. La UI distingue tres estados: sin CLI, token sin usar y conectada.
- **JAJ-66 y JAJ-86 (LLM en la ingesta):** la ingesta corre en el backend, así que su LLM necesita el modo API key o el de demo. Otra opción es exponer la clasificación de huecos como tool, para que la haga la CLI del usuario.
- **ADR 0001:** no cambia. El proveedor solo decide quién corre el loop.

## Pendientes

- Verificar el soporte de MCP por HTTP de Codex CLI.
- Leer los Commercial Terms de Anthropic sobre apps que piden pegar la API key del usuario.
- Autenticación del MCP en producción: el token de Branchpoint por ahora; después, OAuth de MCP.
