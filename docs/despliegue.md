# Despliegue en Render

Branchpoint corre en Render (JAJ-62). Render solo se puede conectar a repos propios, no al de la org, así que despliega desde un **espejo personal**: `dvillas28/branchpoint` (privado), siguiendo el README raíz.

| Pieza | Servicio | URL |
|---|---|---|
| Frontend | `branchpoint` (static site) | https://branchpoint.onrender.com |
| Backend | `branchpoint-api` (web service Python, plan free, virginia) | https://branchpoint-api-laq9.onrender.com |
| Base de datos | Supabase `branchpoint` (`sa-east-1`) | ver `docs/supabase-local.md` |

Los dos servicios despliegan la rama `main` del espejo cada vez que cambia.

## Publicar una versión

1. Mergear la PR de `dev` a `main` en el repo de la org (AGENTS.md) con **"Create a merge commit"**, nunca con squash. Con squash, `main` recibe un commit que `dev` no tiene, y la próxima release vuelve a mostrar todos los commits viejos y choca en los archivos que cambiaron (pasó con la #41).
2. Si la release trae migraciones nuevas, aplicarlas a producción **antes** de empujar (ver "Producción" en `docs/supabase-local.md`).
3. Empujar `main` al espejo. Desde una laptop con el doble push del README configurado:

   ```bash
   git checkout main && git pull && git push
   ```

   Render despliega solo en 1 o 2 minutos. El espejo no se sincroniza solo: si nadie empuja, Render sigue con el `main` anterior.

## Cómo se construye

**Backend** (`branchpoint-api`)

* Build: `cd backend && pip install -e .`
* Start: `cd backend && uvicorn app.api.main:app --host 0.0.0.0 --port $PORT`
* Variables:

| Variable | Valor | Nota |
|---|---|---|
| `PYTHON_VERSION` | `3.12.8` | |
| `DATABASE_URL` | URL del **Transaction pooler** de Supabase (puerto `6543`) | Secreta. La conexión directa (`db.<ref>.supabase.co`) es solo IPv6 y Render no llega: falla con `Network is unreachable` |
| `BRANCHPOINT_CORS_ORIGINS` | `https://branchpoint.onrender.com` | |
| `BRANCHPOINT_FRONTEND_URL` | `https://branchpoint.onrender.com` | A dónde vuelve el callback de GitHub |
| `SUPABASE_URL` | `https://znkeccrcschfsslngfqv.supabase.co` | Con ella, las rutas de proyectos y de GitHub piden sesión (JAJ-78). No usar `BRANCHPOINT_AUTH=off` en producción |
| `BRANCHPOINT_API_URL` | `https://branchpoint-api-laq9.onrender.com` | Su `/github/callback` es el `redirect_uri` del OAuth (JAJ-84) |
| `GITHUB_APP_ID`, `GITHUB_APP_SLUG`, `GITHUB_APP_CLIENT_ID` | `5861305`, `branchpoint-dev`, `Iv23liRbCZBiy2ZyzhBr` | No son secretas |
| `GITHUB_APP_CLIENT_SECRET` | el client secret de la app | Secreta |
| `GITHUB_APP_PRIVATE_KEY_PATH` | `/etc/secrets/github-app.pem` | La private key va como **Secret File** de Render con ese nombre, no pegada en una variable |
| `BRANCHPOINT_MCP_ALLOWED_HOSTS` | `branchpoint-api-laq9.onrender.com,branchpoint-api-laq9.onrender.com:*` | Los `Host` que acepta `/mcp` (protección contra DNS rebinding, JAJ-67). Sin ella, solo localhost: la CLI del usuario no se puede conectar a producción |
| `BRANCHPOINT_CHAT_DEMO` | sin definir | Con `on` y la credencial del equipo, el chat del editor funciona sin la key del usuario (30 mensajes por día). Apagado por defecto |

Sin las variables `GITHUB_APP_*`, `/github/*` responde 503. No configurarlas mientras el backend corra sin login: cualquiera vería y podría analizar los repos de las instalaciones.

## GitHub App en producción

Una sola app (`branchpoint-dev`) sirve para producción y para local. Su configuración en https://github.com/settings/apps/branchpoint-dev:

* **Callback URL:** `https://branchpoint-api-laq9.onrender.com/github/callback` y `http://localhost:8000/github/callback`. El orden no importa, porque el backend manda `redirect_uri`.
* **"Request user authorization (OAuth) during installation":** desmarcado. Con esa opción, GitHub vuelve siempre a la primera Callback URL y no se puede elegir otra.
* **Setup URL:** vacía.
* **Homepage:** `https://branchpoint.onrender.com`.

El flujo: el usuario instala la app en otra pestaña, vuelve y pulsa «Listo, ya la instalé». Eso lanza el OAuth web con `redirect_uri`, y el backend guarda las instalaciones que ve el usuario.

**Frontend** (`branchpoint`)

* Build: `cd frontend && corepack enable && pnpm install --frozen-lockfile && pnpm generate`
* Publica: `frontend/.output/public`
* Variables: `NODE_VERSION=24` y `NUXT_PUBLIC_API_BASE=https://branchpoint-api-laq9.onrender.com`. La URL del backend queda compilada en el build, así que si cambia hay que redesplegar el frontend.

## Problemas comunes

* **El primer request tarda cerca de 1 minuto.** El plan free duerme el backend después de 15 minutos sin tráfico. Antes de una demo, abrir `/health` para despertarlo.
* **GitHub responde `redirect_uri_mismatch`.** `BRANCHPOINT_API_URL` + `/github/callback` tiene que estar exacto en las Callback URL de la app.
* **Un repo grande falla al analizarse.** El tarball se lee entero en memoria y el plan free tiene 512 MB. El tope es de 80 MB comprimido (`BRANCHPOINT_MAX_TARBALL_MB`).
* **`/projects` responde 500 con `PoolTimeout`.** Revisar que `DATABASE_URL` sea la del pooler (ver la tabla).
* **El navegador bloquea las llamadas (CORS).** `BRANCHPOINT_CORS_ORIGINS` tiene que tener el dominio exacto del frontend, con `https://` y sin `/` final.
