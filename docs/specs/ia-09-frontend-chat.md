# IA-9: Frontend: adjuntos y tarjeta de evidencia en el chat

**Área:** frontend · **Depende de:** los contratos de IA-6 e IA-7 (se puede empezar con mocks) · **Tamaño:** M

## Objetivo

Que el usuario adjunte imágenes y logs en el chat del editor y vea qué evidencia le falta al modelo.

## Leer antes

* `frontend/app/composables/useEditorChat.ts`: `send`, `finishTurn`, el historial.
* `frontend/app/services/chat-stream.ts`: `ChatEvent`, `ChatTurn`.
* `frontend/app/services/editor-api.ts`: `chat()`.
* `frontend/app/components/editor/EditorAgentPanel.vue` y `AgentToolCall.vue`.
* `frontend/app/components/editor/types.ts`: `ChatMessage`.
* Las skills `frontend-design` y `shadcn-vue` del repo para todo lo visual.

## Contrato del backend

Adjuntos (IA-6). Todas piden sesión:

* `POST /projects/{id}/attachments` con `{filename, media_type, bytes}` → `{id, kind, upload_url, expires_at}`.
* `PUT upload_url` con el archivo y su `Content-Type`.
* `POST /projects/{id}/attachments/{aid}/complete` → 204.
* `GET /projects/{id}/attachments` → lista.
* `DELETE /projects/{id}/attachments/{aid}`.

Límites: imágenes PNG, JPEG, WebP o GIF de hasta 5 MB; logs `.log`, `.txt`, `.csv`, `.json` o `.ndjson` de hasta 10 MB; 5 adjuntos por mensaje.

Chat (IA-7):

* Cada mensaje del usuario puede llevar `attachments: string[]`.
* El evento `done` trae `evidence: {pending: [{field, ask, accepts}], total_assumptions}`.

## Cambios

### 1. Servicio y composable de adjuntos

* `frontend/app/services/attachments-api.ts`: las cinco llamadas, con el token de sesión como hace `editor-api.ts`.
* `frontend/app/composables/useChatAttachments.ts`: lista de borradores con estado `uploading`, `ready` o `error`, y funciones `add(files)`, `remove(id)` y `clear()`. Valida tipo y tamaño antes de pedir la URL. Sube en paralelo.

### 2. Compositor del chat

En `EditorAgentPanel.vue`:

* Botón de adjuntar con un `<input type="file" multiple>` oculto. También aceptar pegar una imagen desde el portapapeles y soltar archivos sobre el panel.
* Una fila de chips sobre el campo de texto: nombre, tamaño, estado y un botón para quitar. Las imágenes muestran miniatura con `URL.createObjectURL` (liberarla al quitar).
* Enviar queda deshabilitado mientras algún adjunto esté subiendo.
* Sin sesión, el botón aparece deshabilitado con el texto "Inicia sesión para adjuntar archivos".
* Los errores del backend (422 y 401) se muestran en el chip, con el mensaje que viene en `error.message`.

### 3. Envío e historial

* `ChatTurn` gana `attachments?: string[]`. `send(text, expectedSource, attachmentIds)` los manda en el último mensaje.
* `ChatMessage` de rol `user` gana `attachments?: {id, filename, kind}[]` para dibujarlos en la burbuja.
* Al guardar el turno en `history`, quitar los ids de imágenes (el backend no las reenvía) y conservar los de logs.

### 4. Tarjeta de evidencia

* `ChatEvent` de tipo `done` gana `evidence?`.
* Componente nuevo `frontend/app/components/editor/EvidenceRequestCard.vue`: se muestra bajo el último mensaje del agente cuando `pending` no está vacío. Lista cada pedido (`ask`) con un botón "Subir", que abre el selector filtrado por `accepts`, y un enlace "No tengo este dato".
* "No tengo este dato" manda al chat el mensaje "No tengo ese dato: sigue con los supuestos." y oculta ese pedido durante la sesión del navegador.
* La tarjeta se reemplaza con cada `done`: no se acumulan.

### 5. Resultados de las tools nuevas

En `toolResult` de `useEditorChat.ts`, un resumen corto para `analyze_log` ("41,2 req/s pico · 12 endpoints") y para `apply_log_traffic` ("Versión N con tráfico observado"). El resto sigue con "Resultado disponible".

## Criterios de aceptación

* Tests con vitest para `useChatAttachments` (validación de tipo y tamaño, estados, tope de 5) y para el manejo de `done.evidence` en `useEditorChat`.
* `npm run typecheck` y el lint del repo pasan.
* A mano, con el backend local: subir una imagen y un log, enviarlos, ver los chips en la burbuja, ver la tarjeta de evidencia y verla desaparecer después de aplicar el tráfico del log. Adjuntar capturas a la PR.
* Con teclado: el botón de adjuntar y los de quitar tienen foco visible y `aria-label`.
* En modo demo sin backend (`editor-mock.ts`) el chat sigue funcionando y el botón de adjuntar queda deshabilitado.

## Fuera de alcance

* Vista previa del contenido de un log.
* Historial persistente entre recargas.
