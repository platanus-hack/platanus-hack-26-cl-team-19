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

## Validaciones

```bash
pnpm format:check
pnpm lint
pnpm typecheck
pnpm test --run
pnpm build
```

Para aplicar el formato automáticamente, ejecuta `pnpm format`.
