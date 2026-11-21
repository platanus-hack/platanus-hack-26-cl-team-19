# IA-10: Frontend: varios repos en el proyecto y el diagrama

**Área:** frontend · **Depende de:** el contrato de IA-5 (se puede empezar con mocks); parte de IA-3 e IA-4 · **Tamaño:** M

## Objetivo

Crear un proyecto a partir de varios repos, ver el progreso del análisis de cada uno y distinguir en el diagrama lo que se simula de lo que no.

## Leer antes

* `frontend/app/components/projects/NewProjectSheet.vue` y `frontend/app/composables/useGithubConnection.ts`, como queden después de IA-3 (proveedor, credencial y cuota ya están ahí).
* `frontend/app/services/github-api.ts`.
* `frontend/app/services/editor-view.ts`: cómo llegan `DiagramNode` y `DiagramEdge` desde `POST /graph`.
* `frontend/app/components/editor/ArchitectureDiagram.vue`, `component-kinds.ts` y `types.ts`. La PR #59 ya muestra los componentes con su evidencia y procedencia.
* Las skills `frontend-design` y `shadcn-vue` del repo.

## Contrato del backend

`POST /github/ingestions` (IA-5):

```json
{"repos": [{"full_name": "org/api", "branch": "main"}, {"full_name": "org/worker", "branch": "main"}], "name": "Tienda", "provider": "anthropic", "primary": "org/api"}
```

* Entre 1 y 4 repos. `primary` es obligatorio con más de uno.
* Cada repo descuenta 1 de la cuota de extracción. Si no alcanza para todos: 429 `team_extract_quota`.

`GET /github/ingestions/{id}` agrega:

```json
{
  "llm_steps": 12,
  "cost": {"value": 0.42, "unit": "US$", "label": "ESTIMADO", "source": "..."},
  "repos": [{"full_name": "org/api", "status": "running", "endpoints": null, "llm_steps": 12}]
}
```

`llm_steps` y `cost` vienen de IA-4. `cost` puede ser `null`.

`POST /graph`: cada nodo gana `repo` y `simulated`.

`GET /projects`: mantiene `repo` (el principal) y agrega `repos`.

## Cambios

### 1. Nuevo proyecto con varios repos

En `NewProjectSheet.vue`:

* El selector de repo pasa a una lista: "Agregar otro repo" hasta 4, cada fila con repo, rama y un botón para quitar. No se puede elegir dos veces el mismo repo.
* Con más de un repo, un control para marcar el principal, con la ayuda: "Branchpoint simula un servicio. Los demás aparecen en el diagrama como dependencias."
* El texto de la cuota (IA-3) pasa a contar repos: "Este análisis usa 2 de los 5 que te quedan hoy". Si no alcanza, deshabilitar el botón y mostrar el enlace a Configuración.

### 2. Progreso

* Con un repo: bajo la etapa de análisis, "Analizando con IA · paso N", con `llm_steps`.
* Con varios: una fila por repo con su estado y su paso. Un secundario en `failed` se muestra como aviso y no detiene el flujo.
* Al terminar, mostrar el costo si `cost` no es `null`, con su etiqueta `ESTIMADO`.

### 3. Diagrama

En `editor-view.ts` y `types.ts`:

* `DiagramNode` gana `repo?: string` y `simulated?: boolean`, tomados de `POST /graph`. Si `simulated` no viene (modelos antiguos y de ejemplo), se trata como `true`.

En `ArchitectureDiagram.vue`:

* Los nodos con `simulated: false` se dibujan atenuados, con la etiqueta "No simulado".
* El estado de saturación y el cuello de botella se pintan solo en los nodos simulados.
* Con más de un repo en el proyecto, mostrar el nombre del repo bajo el nombre del componente.

En `EditorInspector.vue`: al seleccionar un nodo no simulado, explicar en una línea por qué ("Viene de org/worker. Branchpoint simula solo org/api.") y mostrar su tecnología y cantidad de endpoints.

### 4. Lista de proyectos

En `projects.vue` y `RepositorySidebar.vue`: mostrar todos los repos del proyecto, con el principal primero y marcado.

## Criterios de aceptación

* Tests con vitest: `editor-view.ts` con nodos que traen `simulated: false` y con nodos sin el campo (regresión con un sample existente); la validación de la lista de repos (máximo 4, sin repetidos, principal obligatorio).
* `npm run typecheck` y el lint pasan.
* A mano, con el backend local: crear un proyecto con dos repos, ver las dos filas de progreso, abrir el editor y ver los dos servicios, uno atenuado. Capturas en la PR.
* Un proyecto de un solo repo se crea y se ve igual que antes de esta PR.
* El diagrama con 12 componentes no se sale del panel ni superpone nodos. Si el layout actual no alcanza, anotarlo en la PR antes de cambiarlo.

## Fuera de alcance

* Editar el diagrama a mano.
* Volver a analizar un proyecto existente.
* Rehacer el layout del diagrama.
