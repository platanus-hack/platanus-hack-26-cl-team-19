# Frontend

Aplicación web construida con Nuxt 4, Vue 3 y TypeScript.

## Requisitos

- Node.js 24
- pnpm 11.5.2, administrado mediante Corepack

## Desarrollo local

```bash
corepack enable
pnpm install
pnpm dev
```

La aplicación queda disponible en `http://localhost:3000`.

## Probar el editor

Desde la home, pulsa **Ver proyectos** para abrir `/projects`. El proyecto
de demostración muestra sus repos y ramas. Abre el editor para cambiar de repo
en la barra lateral y volver a **Mis proyectos**. Con `pnpm dev` el editor funciona con
datos de demostración. El dashboard conserva las versiones de demo en la sesión
de esa pestaña. Con la URL de FastAPI y Supabase Auth configuradas, el frontend envía la sesión
a las rutas de proyectos. Configura también `SUPABASE_URL` en FastAPI para que
valide esa sesión y filtre los proyectos por usuario.

Para probar FastAPI directamente en desarrollo, arranca los dos procesos desde la
raíz del repo, en terminales separadas.

```bash
cd backend
python3.12 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m uvicorn app.api.main:app --port 8000
```

```bash
cd frontend
NUXT_PUBLIC_API_BASE=http://127.0.0.1:8000 pnpm dev
```

1. En [el editor](http://localhost:3000/editor), abre
   `full-stack-fastapi-template`. FastAPI entrega el modelo de ese repo y crea
   un proyecto con v1. Puedes probarlo sin conectar GitHub ni Supabase.
2. En **Escenarios**, elige **CyberDay** y pulsa **Simular**. Revisa la serie por
   segundo y el cuello de botella. En **Costos** puedes pedir el costo mensual.
3. En **Versiones**, cambia **Réplicas de la API** de 1 a 3 y pulsa
   **Guardar versión**. En **Comparar**, ejecuta la comparación entre v1 y v2.

FastAPI guarda los proyectos en memoria por defecto. Para persistirlos en Postgres,
configura `DATABASE_URL` según la [guía de Supabase](../docs/supabase-local.md).
Si usas otro puerto para Nuxt, agrega su origen a `BRANCHPOINT_CORS_ORIGINS`
al iniciar el backend.

## Sistema de diseño

Abre [`/design`](http://localhost:3000/design) para revisar los tokens en tema
claro u oscuro. Branchpoint es un banco de trabajo de observabilidad para
ingenieros, con el grafo y la evidencia técnica en primer plano. Las referencias
son la densidad de Grafana, la jerarquía de Linear y las referencias de código de
GitHub.

La fuente de verdad está en [tailwind.css](app/assets/css/tailwind.css). Usa los
roles semánticos de interfaz para fondos, texto, bordes y acciones. Usa
`status-*` para saturación y `source-*` para procedencia.

Tres colores de marca, fuera de la escala de grises:

- `primary` (índigo): acción principal, foco y selección.
- `highlight` (magenta): lo que bifurca o propone el agente, como "Aplicar" en
  una propuesta y el lado nuevo de un diff. Úsalo poco, para que se note.
- `info` (cian): datos y aristas del diagrama.

Acompaña el color de estado con una etiqueta visible y un icono. Los valores de
las muestras son ilustrativos.

Tailwind 4 y el registro de shadcn-vue se configuran en este proyecto. La muestra
de fundamentos corresponde a JAJ-36. El catálogo de componentes reutilizables
corresponde a JAJ-39.

## Validaciones

```bash
pnpm format:check
pnpm lint
pnpm typecheck
pnpm test --run
pnpm build
```

Para aplicar el formato automáticamente, ejecuta `pnpm format`.
