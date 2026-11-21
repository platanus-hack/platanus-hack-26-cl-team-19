# Despliegue en Render

Branchpoint corre en Render (JAJ-62). Render solo se puede conectar a repos propios, no al de la org, así que despliega desde un **espejo personal**: `dvillas28/branchpoint` (privado), siguiendo el README raíz.

| Pieza | Servicio | URL |
|---|---|---|
| Frontend | `branchpoint` (static site) | https://branchpoint.onrender.com |
| Backend | `branchpoint-api` (web service Python, plan free, virginia) | https://branchpoint-api-laq9.onrender.com |
| Base de datos | Supabase `branchpoint` (`sa-east-1`) | ver `docs/supabase-local.md` |

Los dos servicios despliegan la rama `main` del espejo cada vez que cambia.

## Publicar una versión

1. Mergear la PR de `dev` a `main` en el repo de la org (AGENTS.md).
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
| `BRANCHPOINT_AUTH` | `off` | Temporal: el frontend todavía no tiene login (JAJ-77) |

Las variables `GITHUB_APP_*` **no** están en producción a propósito. Con `BRANCHPOINT_AUTH=off`, cualquiera vería y podría analizar los repos de la instalación, así que `/github/*` responde 503 hasta JAJ-77 y JAJ-84.

**Frontend** (`branchpoint`)

* Build: `cd frontend && corepack enable && pnpm install --frozen-lockfile && pnpm generate`
* Publica: `frontend/.output/public`
* Variables: `NODE_VERSION=24` y `NUXT_PUBLIC_API_BASE=https://branchpoint-api-laq9.onrender.com`. La URL del backend queda compilada en el build, así que si cambia hay que redesplegar el frontend.

## Problemas comunes

* **El primer request tarda cerca de 1 minuto.** El plan free duerme el backend después de 15 minutos sin tráfico. Antes de una demo, abrir `/health` para despertarlo.
* **`/projects` responde 500 con `PoolTimeout`.** Revisar que `DATABASE_URL` sea la del pooler (ver la tabla).
* **El navegador bloquea las llamadas (CORS).** `BRANCHPOINT_CORS_ORIGINS` tiene que tener el dominio exacto del frontend, con `https://` y sin `/` final.
