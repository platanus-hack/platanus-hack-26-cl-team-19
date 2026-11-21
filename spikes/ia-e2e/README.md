# Prueba de punta a punta de las specs de IA

Prueba conjunta de las 11 specs de [`docs/specs/`](../../docs/specs/README.md) (Linear M6, PRs #69 a #81), con tres proyectos de juguete. Corre la app real en local; solo dos piezas son falsas:

| Pieza | Real o falsa | Por qué |
|---|---|---|
| Backend, rutas, Postgres, Supabase Auth y Storage (`npx supabase start`) | real | |
| Analizador (`analyze_repo`), `check_evidence`, motor, costos, cuota | real | |
| Frontend (`nuxt dev`) en el navegador | real | |
| **GitHub** | `LocalGitHub` (`backend.py`): sirve `toys/` como repos de una instalación | No se crean repos públicos para la prueba |
| **LLM** | `ScriptedAnalyst` (`analyst.py`) en la ingesta y `ScriptedChat` (`backend.py`) en el chat | No había keys de Anthropic ni OpenAI. El analista usa las tools reales (`grep`) y su entrega pasa por el schema y `check_evidence` |

La calidad de un LLM real leyendo repos la mide IA-0 (`spikes/ia-0-analizador`), no esta prueba.

## Proyectos de juguete

| Repo | Stack | Qué tiene |
|---|---|---|
| `toys/shop-api` | Python, FastAPI, SQLAlchemy | 3 endpoints. `POST /orders` llama a `http://payments:3000/charges`. Compose con Postgres y Redis |
| `toys/payments` | TypeScript, Express, Prisma | 2 endpoints |
| `toys/notifications` | Go, Gin | 2 endpoints |

## Cómo correrla

```bash
npx supabase@3.2.0 start -x studio,edge-runtime,logflare,vector,realtime
npx supabase@3.2.0 migration up
backend/.venv/bin/python spikes/ia-e2e/session.py            # imprime el id del usuario de prueba
E2E_STEP_DELAY_S=1.2 backend/.venv/bin/python spikes/ia-e2e/backend.py <id del usuario>
cd frontend && NUXT_PUBLIC_API_BASE=http://localhost:8000 NUXT_PUBLIC_SUPABASE_URL=http://127.0.0.1:54321 \
  NUXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=sb_publishable_ACJWlzQHlZjBrEguHvfOxg_3BJgxAaH npx nuxt dev --port 3000
```

Después, en http://localhost:3000, pegar en la consola el contenido de `spikes/ia-e2e/.e2e/inject.js` para quedar con sesión. `E2E_STEP_DELAY_S` hace esperar al analista en cada vuelta, para alcanzar a ver el progreso.

## Qué se probó (2026-11-21)

| # | Spec | Prueba | Resultado |
|---|---|---|---|
| 1 | IA-3, IA-2 | Nuevo proyecto con `toys/payments`: la hoja dice "Te quedan 10 de 10 análisis con la key de Branchpoint hoy" | Proyecto creado con 2 endpoints; "Costo del análisis: US$0,10 (ESTIMADO)"; diagrama API → BD como antes |
| 2 | IA-5, IA-10 | Nuevo proyecto con `shop-api` (principal), `notifications` y `payments` | La hoja muestra 3 filas, el principal y "Este análisis usa 3 de los 8 que te quedan hoy". Proyecto con los 3 endpoints del principal, US$0,30 y cuota en 5 |
| 3 | IA-5 | Paso externo `httpx.post("http://payments:3000/charges")` de `shop-api` | Enlazado al servicio `payments` (arista `POST /orders` → payments). `notifications` aparece sin enlaces |
| 4 | IA-10 | Diagrama del proyecto de 3 repos | `payments` y `notifications` atenuados con "No simulado · <repo>". La barra lateral lista los 3 repos con `toys/shop-api` como principal |
| 5 | IA-10 | Inspector de `payments` | "Viene de toys/payments. Branchpoint simula solo toys/shop-api." y "express · 2 endpoints" |
| 6 | IA-10 | Simular CyberDay | La saturación se pinta solo en los nodos del principal |
| 7 | IA-10 | Progreso con dos repos (`notifications` + `payments`) | Una fila por repo con "Analizando · paso N" y el botón "Analizando con IA · paso N"; al final, US$0,20 |
| 8 | IA-7, IA-9 | Chat del proyecto de 3 repos con un log nginx de 560 líneas adjunto | `analyze_log`: "8 req/s pico · 3 endpoints". `apply_log_traffic`: "Versión 2 con tráfico observado" (8,0 req/s, `OBSERVADO`) |
| 9 | IA-6, IA-9 | Chat del proyecto de la tienda con una imagen y un log (antes, en la PR de IA-9) | Subida firmada a Storage, `complete` 204, chips en la burbuja, tarjeta de evidencia que se actualiza y "No tengo este dato" |
| 10 | IA-8 | `add_cache` y después `remove_cache` en `GET /items` (API de ops) | Costo US$0 → 61,91 → 0. `remove_pooler` sin pooler: 422 "El proyecto no tiene pooler." |
| 11 | IA-10 | Versión con 12 componentes | Entran en el panel sin superponerse. Los que no toca ningún paso quedan apilados en la primera columna: el layout no se cambió (fuera de alcance) |
| 12 | IA-10 | "Mis proyectos" | Cada tarjeta lista sus repos con el principal primero y marcado |

## Lo que encontró la prueba y se corrigió en la PR de IA-10

- La hoja mandaba el cuerpo de un solo repo aunque hubiera filas extra: el proyecto quedaba con un repo. El reemplazo de la llamada no había aplicado.
- La cuota de la hoja no se refrescaba después de un análisis.
- "Agregar otro repo" seguía visible con el proyecto ya creado.

## Lo que no cubre

- Un LLM real (calidad, tiempo y costo reales): IA-0.
- La GitHub App real: las rutas de GitHub y los tarballs son los de `LocalGitHub`. El flujo real de la App lo cubren sus propios tests y la PR de JAJ-57.
- OpenAI: el selector de proveedor se probó solo con Anthropic (el LLM falso es el mismo para los dos).
