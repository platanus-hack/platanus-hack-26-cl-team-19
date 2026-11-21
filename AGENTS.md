# AGENTS.md

Instrucciones para agentes que trabajan en este repositorio.

## Ramas

- `main`: solo código productivo. No se hace commit ni push directo.
- `dev`: rama de integración. Todas las PRs de features apuntan a `dev`. Cuando se acumulan cambios estables, se abre una PR de `dev` a `main`.
- Ramas de trabajo: `<username>/<purpose>/<descripcion-corta>`
  - `<username>`: usuario de Linear de quien trabaja la rama, el mismo prefijo que usa Linear en sus nombres de rama (por ejemplo `dvillasc`).
  - `<purpose>`: tipo de cambio, uno de `feat`, `fix`, `docs`, `chore`, `refactor`, `test`.
  - `<descripcion-corta>`: kebab-case, en minúsculas. Si hay issue de Linear, partir con su ID (por ejemplo `jaj-7-extraccion-grafo`).
  - Ejemplo: `dvillasc/feat/jaj-7-extraccion-grafo`.

## Skills

Las skills del repo viven en `.agents/skills/`, una carpeta por skill con su `SKILL.md`. Es la fuente única para todos los agentes.

- `.claude/skills` es un symlink a `.agents/skills`, para que Claude Code las cargue.
- Incluye las skills de Matt Pocock ([mattpocock/skills](https://github.com/mattpocock/skills) v1.3.1, licencia MIT en `.agents/skills/LICENSE-mattpocock-skills`).
- Para agregar o actualizar una skill, se edita en `.agents/skills/`, nunca en `.claude/skills/`.

## Flujo

1. Crear la rama de trabajo desde `dev` actualizado.
2. Abrir la PR con base `dev`, nunca `main`.
3. La PR de `dev` a `main` se abre aparte, cuando el equipo lo decide.
