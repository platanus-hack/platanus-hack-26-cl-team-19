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

## Sistema de diseño

Abre [`/design`](http://localhost:3000/design) para revisar los tokens en tema
claro u oscuro. Branchpoint es un banco de trabajo de observabilidad para
ingenieros, con el grafo y la evidencia técnica en primer plano. Las referencias
son la densidad de Grafana, la jerarquía de Linear y las referencias de código de
GitHub.

La fuente de verdad está en [tailwind.css](app/assets/css/tailwind.css). Usa los
roles semánticos de interfaz para fondos, texto, bordes y acciones. Usa
`status-*` para saturación y `source-*` para procedencia. Acompaña el color de
estado con una etiqueta visible y un icono. Los valores de las muestras son
ilustrativos.

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
