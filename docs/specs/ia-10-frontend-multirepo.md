# IA-10: Frontend: varios repos y diagrama de componentes

**Área:** frontend · **Depende de:** los contratos de IA-3 e IA-5 (se puede empezar con mocks) · **Tamaño:** M

## Objetivo

Crear un proyecto a partir de varios repos de cualquier tecnología, ver el progreso de la extracción con IA y dibujar el diagrama con los componentes del grafo.

## Leer antes

* `frontend/app/components/projects/NewProjectSheet.vue` y `frontend/app/composables/useGithubConnection.ts`.
* `frontend/app/services/github-api.ts`.
* `frontend/app/services/editor-view.ts`: cómo se arman hoy `DiagramNode` y `DiagramEdge` desde el modelo.
* `frontend/app/components/editor/ArchitectureDiagram.vue`, `component-kinds.ts` y `types.ts`.
* `frontend/app/composables/useApiCredentials.ts`: cuota y keys.
* Las skills `frontend-design` y `shadcn-vue` del repo.

## Contrato del backend

`POST /github/ingestions` (IA-5):

```json
{"repos": [{"full_name": "org/api", "branch": "main"}], "project_name": "Tienda", "provider": "anthropic", "primary": "org/api"}
```

`GET /github/ingestions/{id}` agrega `stage: "extraccion_ia"`, `extractor: "ast" | "llm" | "mixto"`, `llm_steps` y `cost`.

Errores nuevos: 429 `team_extract_quota` al crear.

`GET /credentials/chat-settings` agrega `extract: {remaining, limit}` (IA-2).

El modelo de cada versión trae `graph`:

```json
{
  "components": [{"id": "api", "kind": "service", "name": "api", "repo": "org/api", "technology": "express", "origin": "llm", "evidence": {"file": "src/app.ts", "line": 12}}],
  "edges": [{"source": "api", "target": "db", "kind": "reads", "origin": "llm", "evidence": {"file": "...", "line": 1}}],
  "primary": "api",
  "warnings": []
}
```

`kind` de componente: `service`, `db`, `cache`, `queue`, `worker`, `external`, `proxy`, `storage`.

## Cambios

### 1. Nuevo proyecto con varios repos

En `NewProjectSheet.vue`:

* El selector de repo pasa a una lista: "Agregar otro repo" hasta 4, cada fila con repo, rama y un botón para quitar.
* Con más de un repo, un control para marcar el principal, con la ayuda: "Branchpoint simula un servicio. Los demás aparecen en el diagrama como dependencias."
* Un aviso fijo bajo la lista: "Si el repo no es FastAPI, el análisis usa IA", junto a la cuota que queda ("2 de 2 análisis con IA hoy") o "Usarás tu API key de Anthropic" si tiene una personal seleccionada. Enlace a Configuración.
* Selector de proveedor (Anthropic u OpenAI), con el mismo criterio que el chat.
* Con 429 `team_extract_quota`: mostrar el mensaje del backend y el enlace a Configuración. No reintentar solo.

### 2. Progreso

* Agregar la etapa `extraccion_ia` a la lista de etapas, con el texto "Analizando con IA · paso N" usando `llm_steps`.
* Al terminar, si `extractor` no es `ast`: mostrar el costo (`cost.value` con `cost.unit`) y su etiqueta `ESTIMADO`.

### 3. Diagrama desde el grafo

En `editor-view.ts`:

* Si el modelo trae `graph`, los nodos salen de `graph.components` y las aristas de `graph.edges`. Si no (proyectos antiguos y modelos de ejemplo), queda el cálculo de hoy.
* Ampliar `ComponentKind` y `component-kinds.ts` con `worker`, `external`, `proxy` y `storage` si faltan, con icono y etiqueta.
* `DiagramNode` gana `origin?: "ast" | "iac" | "llm"`, `repo?: string` y `simulated?: boolean` (verdadero solo para `graph.primary` y los recursos que el motor modela: DB, caché y colas).
* El estado de saturación y el cuello de botella se siguen pintando solo en los nodos simulados.

En `ArchitectureDiagram.vue`:

* Los nodos no simulados se dibujan atenuados, con la etiqueta "No simulado".
* Los nodos con `origin: "llm"` llevan la insignia de procedencia `ESTIMADO` (reutilizar `design/ProvenanceBadge.vue`).
* Con más de un repo, mostrar el nombre del repo bajo el nombre del componente.

En `EditorInspector.vue`: al seleccionar un componente, mostrar su evidencia `archivo:línea` con `design/CodeReference.vue`, y los avisos de `graph.warnings` en una sección plegable.

## Criterios de aceptación

* Tests con vitest de `editor-view.ts`: un modelo con `graph` produce los nodos y aristas del grafo con `simulated` correcto; un modelo sin `graph` produce lo mismo que hoy (test de regresión con un sample existente).
* `npm run typecheck` y el lint pasan.
* A mano, con el backend local y un LLM real o falso: crear un proyecto con dos repos, ver la etapa de IA, abrir el editor y ver los dos servicios, uno atenuado. Capturas en la PR.
* Un proyecto FastAPI de un solo repo se crea y se ve igual que antes, sin etapa de IA ni costo.
* El diagrama con 12 componentes no se sale del panel ni superpone nodos. Si el layout actual no alcanza, anotarlo en la PR antes de cambiarlo.

## Fuera de alcance

* Editar el grafo a mano.
* Volver a analizar un proyecto existente.
* Rehacer el layout del diagrama.
