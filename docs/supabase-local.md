# Supabase local

Cómo levantar Supabase en tu máquina para desarrollar el backend (JAJ-56). El stack local es una copia completa de Supabase (Postgres, Auth, Storage, Studio) en Docker, con las mismas migraciones que el proyecto de producción.

## Requisitos

- **Docker** corriendo. En Linux, tu usuario tiene que poder usar `docker` sin `sudo`.
- **Node 20 o más nuevo**, solo para la CLI de Supabase.
- Unos 3 GB libres para las imágenes de Docker.

La CLI de Supabase **no se instala global**: `package.json` de la raíz la fija en la versión `3.2.0`, así todo el equipo usa la misma. Se corre con `npx supabase …` desde la raíz del repo.

## Primera vez

Desde la raíz del repo:

```bash
npm install
```

```bash
npx supabase start
```

La primera vez descarga las imágenes y tarda varios minutos. Al terminar, aplica las migraciones de `supabase/migrations/` e imprime las URLs y las keys locales.

Después, crea el `.env` del backend a partir del ejemplo:

```bash
cp backend/.env.example backend/.env
```

Y completa las keys con las que imprime:

```bash
npx supabase status -o env
```

| Variable del backend       | Valor de `supabase status`         |
| -------------------------- | ---------------------------------- |
| `DATABASE_URL`             | `DB_URL` (ya viene en el ejemplo)  |
| `SUPABASE_URL`             | `API_URL` (ya viene en el ejemplo) |
| `SUPABASE_PUBLISHABLE_KEY` | `PUBLISHABLE_KEY`                  |
| `SUPABASE_SECRET_KEY`      | `SECRET_KEY`                       |

Las keys locales son de desarrollo y son iguales en todas las máquinas, pero igual `backend/.env` no se commitea.

Con eso, la API guarda los proyectos en el Supabase local. Desde `backend/`:

```bash
uvicorn app.api.main:app --reload --env-file .env
```

Sin `--env-file` (o sin `DATABASE_URL`), la API guarda los proyectos en memoria y se pierden al reiniciarla.

Para correr también los tests de Postgres, desde `backend/`:

```bash
TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres python -m pytest -q
```

Esos tests vacían las tablas, así que solo aceptan una base local. Sin `TEST_DATABASE_URL` se saltan. En el CI corren siempre, con `npx supabase db start`.

## Probar el acceso con GitHub

1. Registra una **OAuth App** de desarrollo en GitHub con
   `http://localhost:54321/auth/v1/callback` como callback. La GitHub App que
   importa repos se configura por separado.
2. Configura Supabase CLI con estas variables en `supabase/.env.local` y
   reinicia el stack con `npx supabase stop` y `npx supabase start`.

   ```dotenv
   SUPABASE_AUTH_EXTERNAL_GITHUB_ENABLED=true
   SUPABASE_AUTH_EXTERNAL_GITHUB_CLIENT_ID=
   SUPABASE_AUTH_EXTERNAL_GITHUB_SECRET=
   ```

3. Crea `frontend/.env` a partir de `frontend/.env.example` y completa
   `NUXT_PUBLIC_SUPABASE_URL` con la URL de la API local y
   `NUXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` con la llave pública que muestra
   `npx supabase status`. El secreto de GitHub solo va en la configuración de
   Supabase.
4. Desde `frontend/`, ejecuta `pnpm dev` y abre
   `http://localhost:3000`. Usa **Continuar con GitHub** en la home. Tras autorizar,
   Nuxt recibe el código en `/auth/callback` y abre `/onboarding` la primera vez en ese navegador. Después del onboarding,
   el acceso lleva a `/projects`.

Para el entorno alojado, habilita GitHub en **Authentication → Sign In /
Providers** y configura el callback que muestra Supabase en la OAuth App de
ese entorno. Agrega también la URL del frontend terminada en `/auth/callback`
a las redirecciones autorizadas de Supabase. [Guía de GitHub Auth](https://supabase.com/docs/guides/auth/social-sign-in/auth-github)

## Día a día

| Para                                                      | Comando                 |
| --------------------------------------------------------- | ----------------------- |
| Levantar el stack                                         | `npx supabase start`    |
| Ver URLs y keys                                           | `npx supabase status`   |
| Apagarlo (los datos se mantienen)                         | `npx supabase stop`     |
| Borrar los datos y volver a aplicar todas las migraciones | `npx supabase db reset` |

Con el stack arriba:

- **Studio** (ver tablas y correr SQL): http://127.0.0.1:54323
- **Postgres:** `postgresql://postgres:postgres@127.0.0.1:54322/postgres`
- **API:** http://127.0.0.1:54321
- **Mailpit** (los correos de Auth): http://127.0.0.1:54324

## Cambiar el esquema

El esquema vive **solo** en `supabase/migrations/`. Nunca se edita una migración que ya está en `dev`: un cambio es una migración nueva.

1. Crea el archivo:

   ```bash
   npx supabase migration new nombre_del_cambio
   ```

   Queda vacío en `supabase/migrations/<timestamp>_nombre_del_cambio.sql`. Escribe el SQL ahí.

2. Aplícalo a tu base local:

   ```bash
   npx supabase db push
   ```

   Si algo sale mal, `npx supabase db reset` la deja limpia con todas las migraciones.

3. Commitea la migración en tu PR. Se aplica a producción después del merge (ver abajo).

Después de cambiar el esquema, revisa en Studio el **Advisors → Security Advisor**: avisa de tablas sin RLS y funciones expuestas a la API.

## Producción

El proyecto de producción se llama `branchpoint` (ref `znkeccrcschfsslngfqv`, región `sa-east-1`). Para aplicarle migraciones necesitas que te inviten a la organización de Supabase y la contraseña de la base de datos (pídesela a Daniel, no va en el repo).

```bash
npx supabase login
```

```bash
npx supabase link --project-ref znkeccrcschfsslngfqv
```

```bash
npx supabase db push --remote
```

Antes de confirmar, `db push --remote` lista las migraciones que va a aplicar. Revisa que sean solo las que ya están en `dev`.

## Problemas comunes

- **`db push` dice "Local database is up to date" y producción no cambió.** En la CLI 3.x, `db push` apunta al stack local por defecto. Para producción hace falta `--remote`.
- **`supabase: command not found`.** La CLI no está instalada global a propósito: usa `npx supabase …` desde la raíz del repo, después de `npm install`.
- **`port is already allocated` al hacer `start`.** Otro proyecto de Supabase (u otro Postgres) usa los puertos 54321–54324. Apágalo con `npx supabase stop --project-id <su-id>` o `docker ps` para ver qué contenedor es.
- **`permission denied ... docker.sock`.** Tu usuario no está en el grupo `docker`: `sudo usermod -aG docker $USER` y vuelve a iniciar sesión.
- **Una migración nueva quedó vacía al crearla desde un script o un agente.** `migration new` copia lo que llega por stdin al archivo, y sin terminal se queda esperando. Desde un script, usa `npx supabase migration new nombre </dev/null` y escribe el SQL después. Si ya la aplicaste vacía en local, escribe el SQL y corre `npx supabase db reset`.
