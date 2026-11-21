# IA-6: Adjuntos temporales en Supabase Storage

**Área:** backend, DB · **Depende de:** nada · **Tamaño:** M · **Bloquea:** IA-7, IA-9

## Objetivo

Que un usuario con sesión suba imágenes y logs asociados a un proyecto, que el backend pueda leerlos y que se borren solos.

## Leer antes

* `backend/app/api/auth.py`: `current_user`, `owner_of`.
* `backend/app/api/routes/credentials.py`: el patrón de rutas que exigen usuario y devuelven 503 sin Postgres.
* `backend/.env.example`: `SUPABASE_URL`, `SUPABASE_SECRET_KEY`.
* `docs/supabase-local.md` y `supabase/config.toml`.
* `backend/app/github/client.py`: cómo hace HTTP el backend hoy. Usar el mismo cliente, sin dependencias nuevas.

## Diseño

El archivo viaja del navegador a Storage directamente, con una URL firmada. El backend nunca recibe el archivo en una request: solo firma, registra y después descarga cuando una tool lo necesita.

```
navegador ── POST /projects/{id}/attachments ──▶ backend ── firma ──▶ Storage
navegador ── PUT a la URL firmada (el archivo) ───────────────────▶ Storage
navegador ── POST /projects/{id}/attachments/{aid}/complete ──▶ backend (verifica tamaño y tipo)
```

### Storage

* Bucket privado `chat-attachments`, creado por migración (`insert into storage.buckets ...`) con `file_size_limit` de 10 MB y los tipos permitidos.
* Ruta del objeto: `<owner_id>/<project_id>/<attachment_id>/<nombre saneado>`.
* Sin políticas para `anon` ni `authenticated`: solo entra el backend con `SUPABASE_SECRET_KEY` y el navegador con la URL firmada.

### Tabla

Migración nueva y la misma definición en `backend/app/db/schema.sql`:

```sql
create table chat_attachments (
    id            uuid primary key default gen_random_uuid(),
    owner_id      uuid not null references auth.users (id) on delete cascade,
    project_id    uuid not null references projects (id) on delete cascade,
    kind          text not null check (kind in ('image', 'log')),
    filename      text not null,
    media_type    text not null,
    bytes         bigint,
    storage_path  text not null,
    status        text not null default 'pending' check (status in ('pending', 'ready')),
    created_at    timestamptz not null default now(),
    expires_at    timestamptz not null
);
```

Con RLS activado y sin políticas, como `team_chat_usage`.

### Tipos y límites

| `kind` | Tipos | Tamaño |
|---|---|---|
| `image` | `image/png`, `image/jpeg`, `image/webp`, `image/gif` | 5 MB |
| `log` | `text/plain`, `text/csv`, `application/json`, `application/x-ndjson`, extensión `.log` | 10 MB |

* Vencimiento: 24 horas (`BRANCHPOINT_ATTACHMENT_TTL_HOURS`).
* Máximo 20 adjuntos vigentes por proyecto.

### Módulo `backend/app/storage/attachments.py`

Una clase `AttachmentStorage(supabase_url, secret_key)` con:

* `signed_upload(path) -> str`: URL firmada de subida.
* `download(path, max_bytes) -> bytes`.
* `head(path) -> (bytes, media_type)`.
* `delete(paths)`.

Verificar los endpoints REST de Supabase Storage contra su documentación antes de escribirlos. Una implementación en memoria `InMemoryAttachmentStorage` con la misma interfaz, para tests y para correr sin Supabase.

### Rutas (`backend/app/api/routes/attachments.py`)

Todas exigen usuario (401 sin sesión) y que el proyecto sea suyo (404 si no).

| Ruta | Hace |
|---|---|
| `POST /projects/{id}/attachments` con `{filename, media_type, bytes}` | Valida tipo, tamaño y tope. Crea la fila `pending`. Devuelve `{id, kind, upload_url, expires_at}`. |
| `POST /projects/{id}/attachments/{aid}/complete` | Hace `head` en Storage, compara tamaño y tipo con lo declarado y marca `ready`. Si no calza, borra y responde 422. |
| `GET /projects/{id}/attachments` | Lista los `ready` vigentes: `id`, `kind`, `filename`, `bytes`, `created_at`, `expires_at`. |
| `DELETE /projects/{id}/attachments/{aid}` | Borra el objeto y la fila. |

### Limpieza

Sin cron. En cada `POST` y `GET` de adjuntos, borrar antes los vencidos de ese usuario (objeto y fila). Dejar una función `purge_expired(limit=100)` que una tarea futura pueda llamar.

### Métodos del store

En `ProjectStore` (Postgres y en memoria): `create_attachment`, `get_attachment(id, owner)`, `list_attachments(project_id, owner)`, `mark_attachment_ready`, `delete_attachment`, `expired_attachments(owner)`.

## Criterios de aceptación

Con `InMemoryAttachmentStorage` y `TestClient`:

* Subir, completar, listar y borrar funciona de punta a punta.
* Un tipo no permitido o un tamaño mayor al límite responde 422 y no crea fila.
* `complete` con un objeto de tamaño distinto al declarado responde 422 y lo borra.
* Un usuario no ve ni completa los adjuntos de otro (404).
* Sin sesión: 401.
* Un adjunto vencido no aparece en la lista y se borra de Storage en la llamada siguiente.
* El adjunto 21 de un proyecto responde 422.
* El nombre de archivo se sanea: `../../x.png` y nombres con `/` no producen rutas fuera de la carpeta del adjunto.
* Test del store Postgres para los métodos nuevos, junto a `tests/db/test_postgres_store.py`.

## Fuera de alcance

* Mandar los adjuntos al modelo y las tools que los leen: es IA-7.
* La UI: es IA-9.
* PDF y otros formatos.
