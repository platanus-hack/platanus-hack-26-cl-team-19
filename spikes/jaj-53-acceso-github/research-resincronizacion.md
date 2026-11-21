# Reanalizar repositorios y ramas

## Qué hay hoy

En `origin/dev` (`325e544d`), el spike de JAJ-53 descarga un tarball para una referencia dada, extrae el archivo en temporal y ejecuta el analizador AST. Su prueba con un repo privado usó el token OAuth de `gh` y tardó 2,25 s para 3,2 MB. Ese tiempo corresponde a descarga, extracción y AST del prototipo. La integración con el token de instalación y la ingesta del backend se siguen en JAJ-65 y JAJ-57. [Spike JAJ-53](README.md) · [JAJ-65](https://linear.app/jajathom/issue/JAJ-65) · [JAJ-57](https://linear.app/jajathom/issue/JAJ-57)

## MVP recomendado

1. En el editor, seleccionar un repo y una rama remota, y pulsar **Analizar cambios**. GitHub permite listar ramas y obtener el SHA de su punta con `Contents: read`. Resolver la rama al SHA una sola vez y descargar por ese SHA fija el código analizado aunque la rama avance durante la ingesta. Mostrar la rama y el SHA corto del último análisis. [Ramas](https://docs.github.com/en/rest/branches/branches#get-a-branch) · [Tarballs](https://docs.github.com/en/rest/repos/contents#download-a-repository-archive-tar)
2. Si ya hay una ingesta para ese repo, SHA y configuración de extracción, reutilizar su resultado. Si cambió el SHA, ejecutar la misma ingesta que en la importación inicial y crear una versión de origen `repo`. Mantener accesibles las versiones manuales y del agente. Reaplicar sus cambios sobre el nuevo modelo, cuando se necesite, como una acción explícita que valida los endpoints y recursos que todavía existen. [ADR del agente](../../docs/adr/0001-el-llm-opera-sobre-el-modelo-no-lo-extrae.md)
3. Permitir comparar un modelo generado desde la rama principal con otro de una rama de trabajo bajo el mismo escenario. Una rama remota puede borrarse o reescribirse. El modelo persistido y su SHA conservan la procedencia de la simulación. Si el commit deja de estar disponible en GitHub, volver a examinar el código original requeriría conservar un snapshot. [Push de Git](https://docs.github.com/en/get-started/using-git/pushing-commits-to-a-remote-repository) · [Versiones y runs en el esquema](../../supabase/migrations/20261121094836_modelo_de_datos.sql)

En pantalla, el recorrido sería **repo → rama → Analizar cambios → Comparar**. Por ejemplo, comparar `main@a1b2c3d` con `feature/cache@e4f5a6b` en CyberDay. Mostrar primero qué cambió en el modelo y luego las diferencias de simulación. Un diff de Git explica qué archivos cambiaron, mientras que el diff de Branchpoint explica qué cambió en la arquitectura modelada. Si el código ya estaba analizado, mostrar **Al día** y abrir el modelo existente. Si la ingesta falla, mantener disponible el último modelo válido junto al error. [Comparación en FastAPI](../../backend/app/api/routes/projects.py)

## Webhook para mantener las ramas al día

La GitHub App ya pensada para la ingesta también puede recibir `push` con acceso de lectura a Contents. La propuesta para Branchpoint es que **el webhook mantenga actualizado el catálogo de ramas y commits**. Una acción del usuario crea el análisis. Así, un push de otra persona puede aparecer enseguida sin cambiar el modelo que alguien está revisando. [Evento push](https://docs.github.com/en/webhooks/webhook-events-and-payloads#push) · [Ramas](https://docs.github.com/en/rest/branches/branches)

### Qué ve el usuario

1. Al conectar o refrescar un repo, cargar el listado de ramas de GitHub. En el selector mostrar nombre, SHA corto actual y SHA del último análisis exitoso.
2. Al recibir un push, actualizar la rama correspondiente. Si el editor estaba abierto, puede refrescar el estado periódicamente. El usuario sigue viendo los resultados del SHA que abrió.
3. Al seleccionar una rama, mostrar su commit actual y las versiones de Branchpoint ya analizadas para esa rama. Permitir abrir una versión existente o pulsar **Analizar commit**. Marcar **Nueva rama** o **Cambios disponibles** según corresponda.
4. Si la rama avanzó mientras el usuario miraba el selector, mantener el SHA visible y permitir elegir el nuevo. La ingesta descarga el SHA elegido, y **Comparar** acepta los modelos guardados con el mismo escenario y semilla.
5. Cuando haga falta elegir un commit anterior que todavía no se analizó, cargar el historial de GitHub bajo demanda. El webhook informa cambios al extremo de la rama y el historial se obtiene desde la API. [API de commits](https://docs.github.com/en/rest/commits/commits#list-commits) · [Tarballs](https://docs.github.com/en/rest/repos/contents#download-a-repository-archive-tar)

| Estado de la rama | Qué mostramos |
| --- | --- |
| Sin análisis exitoso | **Sin analizar** y la acción para el SHA actual. |
| SHA actual igual al último analizado | **Al día** y acceso al resultado guardado. |
| SHA actual distinto | **Cambios disponibles**, con ambos SHA. |
| Ingesta pendiente o fallida | Estado del SHA solicitado. El último modelo exitoso sigue accesible. |
| Rama eliminada o acceso revocado | Los análisis guardados siguen visibles. El estado indica que no se puede traer código nuevo. |

### Qué haría FastAPI

- Verificar la firma sobre el cuerpo original con el secreto de la GitHub App. Asociar la instalación y el ID de repositorio a las conexiones conocidas. Usar `ref` para distinguir `refs/heads/*` de los tags y registrar la entrega una vez con `X-GitHub-Delivery`. Aceptar y responder rápido tras persistir el aviso o encolarlo. [Validar entregas](https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries) · [Buenas prácticas](https://docs.github.com/en/webhooks/using-webhooks/best-practices-for-using-webhooks)
- Procesar el aviso fuera del request y reconciliar la rama contra GitHub. El payload trae `after` y señales de creación, borrado o force-push. Como pueden faltar entregas o llegar desordenadas, el evento indica qué rama refrescar y GitHub confirma su estado actual. Serializar las actualizaciones para cada repo y rama y ofrecer **Actualizar ramas** como recuperación manual. [Evento push](https://docs.github.com/en/webhooks/webhook-events-and-payloads#push) · [Buenas prácticas](https://docs.github.com/en/webhooks/using-webhooks/best-practices-for-using-webhooks)
- Mantener separados el **SHA remoto actual** y el **último SHA analizado**. El primero pertenece al estado de la rama para la conexión. El segundo sale de una ingesta exitosa de ese repo en el proyecto. Deduplicar la ejecución por repo del proyecto, SHA y configuración del extractor. Conservar qué rama se eligió como procedencia, incluso si dos ramas apuntan al mismo commit.
- Para un primer corte, listar y actualizar ramas manualmente y guardar el SHA en cada análisis. Después, incorporar el webhook que muestra **Cambios disponibles**. Validar con pushes a dos ramas, una entrega duplicada, una antigua recibida tarde, un force-push y un borrado. En todos los casos, la versión abierta debe seguir asociada al mismo SHA.

## Cuánto cambia por etapa

| Capacidad | Complejidad estimada | Qué agrega |
| --- | --- | --- |
| Reanalizar la rama actual o elegir otra rama remota | Baja a media después de JAJ-57 | Selección de rama, resolución y persistencia de SHA, reutilización de ingesta y estados en el editor. |
| Detectar nuevos commits automáticamente | Media | Webhook `push` firmado. Usar `ref` y `after`, mostrar que hay una actualización disponible primero y deduplicar si luego se automatiza el análisis. Considerar borrados, force-push y revocación de acceso. [Evento push](https://docs.github.com/en/webhooks/webhook-events-and-payloads#push) · [Validar entregas](https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries) |
| Probar cambios en el disco del usuario | Media | GitHub expone los cambios publicados. Para los cambios locales, un proceso local explícitamente autorizado puede entregar un snapshot del directorio o se puede usar la ingesta ZIP. Registrar SHA base y hash del snapshot para identificar exactamente qué se simuló. [Push de Git](https://docs.github.com/en/get-started/using-git/pushing-commits-to-a-remote-repository) · [JAJ-58](https://linear.app/jajathom/issue/JAJ-58) |
| Editar y publicar desde Branchpoint | Alta | Edición de archivos, diff, manejo de cambios concurrentes, commit en rama de trabajo y PR. Publicar archivos requiere `Contents: write` y crear PR requiere `Pull requests: write`. Para el MVP, editar en GitHub o en el IDE/CLI del usuario y reanalizar en Branchpoint mantiene el permiso de ingesta de solo lectura. [Escritura de archivos](https://docs.github.com/en/rest/repos/contents#create-or-update-file-contents) · [Crear PR](https://docs.github.com/en/rest/pulls/pulls#create-a-pull-request) |

## Datos

El esquema actual ya guarda `branch` y `commit_sha` por ingesta, y `commit_sha` por versión. Esto alcanza como punto de partida para el reanálisis de un proyecto de un repo. Las versiones se numeran por proyecto y `projects` tiene una sola conexión. Para que cada repo dentro del mismo proyecto tenga su propio historial, migrar a `project_repositories`, asociar ingestas y versiones a esa relación y mantener las referencias a runs existentes. Guardar la rama usada por análisis como procedencia, incluso si después se cambia la rama que se muestra por defecto. Un futuro modelo que combine varios repos necesitaría un manifiesto de SHA por repo. [Esquema de Supabase](../../supabase/migrations/20261121094836_modelo_de_datos.sql)
