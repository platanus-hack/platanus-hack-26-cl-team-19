# Dónde se va el tiempo de importar un repo

[JAJ-146](https://linear.app/jajathom/issue/JAJ-146) · Sigue el paso 1 de "Qué probar después" de [JAJ-126](../jaj-126-ingesta/README.md): una corrida fría con el proveedor real. WSL 2, Python 3.13, rama `dev` `ddb39db`, `claude-opus-5-5` con thinking adaptativo (el modelo de extracción por defecto). Una corrida por repo, el 2026-11-22.

**Resultado.** La descarga del tarball pesa **menos del 1,5 %** del tiempo. El LLM se lleva el **99 %**, y de eso entre el **77 % y el 84 %** es una sola llamada: la entrega final con `submit_architecture`, que genera entre 4.800 y 13.500 tokens de salida. Cachear solo el tarball en Supabase Storage ahorraría ~0,6 s de 43–191 s. Lo que vale la pena cachear es **el resultado del análisis**.

## Fases

| Repo y commit | Tarball | Descarga | Extracción | LLM | Analizador local | IaC + modelo | Total | Vueltas | Costo |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| FastAPI RealWorld `029eb77` | 98,5 KiB | 0,59 s | 22 ms | 110,9 s | 15 ms | 17 ms | **111,6 s** | 7 | US$0,53 |
| Express RealWorld `30b68e1` | 155,4 KiB | 0,61 s | 14 ms | 42,3 s | 8 ms | 7 ms | **42,9 s** | 5 | US$0,26 |
| Django RealWorld `29c9d42` | 66,1 KiB | 0,56 s | 8 ms | 190,6 s | 19 ms | 7 ms | **191,2 s** | 9 | US$0,79 |

Los tres encontraron 19–20 endpoints y ninguna evidencia descartada.

## Las vueltas del LLM

Las vueltas de exploración (`read_file`, `grep`) toman 1,4–4,1 s cada una (salvo un `grep` de 16,8 s en Django) y suman 10–33 s. La entrega final es otra cosa:

| Repo | Vueltas de exploración | Entrega final | Salida de la entrega |
| --- | ---: | ---: | ---: |
| FastAPI | 6 · 17,7 s | 93,3 s | 13.545 tokens |
| Express | 4 · 9,5 s | 32,7 s | 4.823 tokens |
| Django | 7 · 32,6 s | 79,7 s + **78,4 s** | 11.513 + 12.185 tokens |

En Django la primera entrega no pasó `evidence_problems` y el modelo la rehízo entera: la reentrega sola costó 78 s. Los tokens de salida incluyen el thinking; no separamos cuánto es thinking y cuánto es el JSON.

## Qué significa para el caché

En producción, 2 de 5 ingestas repitieron repo y SHA (consulta a `ingestions` del 2026-11-22). Con lo medido, se abren estas palancas, de mayor a menor efecto por esfuerzo:

1. **Cachear el análisis por repo y SHA.** Guardar la salida de `analyze_repo` (la `ArchitectureSubmission`, el uso y los descartes) con clave `(github_repo_id, commit_sha)`. Una reimportación del mismo commit baja de 43–191 s a ~1 s (resolver el SHA y armar el modelo). Cabe en una tabla de Postgres con `jsonb`; no necesita Storage. El acceso se mantiene si se resuelve el SHA con el token de instalación del usuario **antes** de mirar el caché: si GitHub responde, el usuario puede leer ese commit.
2. **Achicar la entrega final.** Es el 80 % del tiempo de una corrida fría. Opciones a medir: thinking acotado o apagado solo en la vuelta de entrega, un modelo más rápido para extraer (`BRANCHPOINT_ANTHROPIC_EXTRACT_MODEL`), o un schema de entrega más compacto.
3. **Corregir la evidencia sin rehacer la entrega.** Cuando falla `evidence_problems`, pedir solo los ítems con problemas en vez de la arquitectura completa. En Django habría ahorrado 78 s.
4. **Análisis incremental para un SHA nuevo.** Partir del análisis del commit anterior y mirar solo los archivos cambiados (`compare` de GitHub). Más complejo; conviene después de 1.
5. **Cachear el tarball en Storage.** ~0,6 s por import. Solo vale si se vuelve a analizar el mismo commit sin caché de análisis (por ejemplo, otro modelo o prompt).

## Implementado: caché del análisis

Se hizo la palanca 1. La tabla `repo_analyses` ([migración](../../supabase/migrations/20261122040000_repo_analyses.sql)) guarda la entrega del LLM por repo de GitHub, commit completo y `ANALYZER_FINGERPRINT` (huella del prompt, las tools y los límites de [analyzer.py](../../backend/app/ingest/analyzer.py)). [`model_from_tarball`](../../backend/app/github/ingestion.py) la consulta antes de llamar al LLM. El tarball se descarga igual y la IaC y el modelo se rearman con el catálogo de hoy. Solo se guardan entregas sin descartes de evidencia. Si el caché falla, se analiza como siempre.

Medido con Claude real y Postgres local, Express RealWorld `30b68e1`: la primera importación tomó **41,7 s** (US$0,26) y la segunda **0,7 s**, sin tokens y con los mismos 20 endpoints.

## Acelerar la primera importación: modelo, effort y fast mode

El caché no ayuda en el onboarding, donde casi siempre es la primera vez que se ve el repo. Se midieron cinco variantes de la llamada al LLM con `measure.py`, una corrida por repo y variante, en paralelo, el 2026-11-22. La calidad sale del comparador de IA-0 ([score.py](../ia-0-analizador/score.py)): endpoints de la referencia encontrados (recall), evidencia válida y pasos de efecto (accesos a DB, caché y servicios citados por endpoint, que es lo que simula el motor).

| Variante | Tiempo total, 3 repos | Por repo (FastAPI · Express · Django) | Costo, 3 repos | Recall | Pasos de efecto (F · E · D) |
| --- | ---: | --- | ---: | --- | --- |
| Opus 5.5 `medium` (hoy) | 329 s | 112 · 41 · 176 s | US$1,52 | 1,00 · 1,00 · 1,00 | 127 · 33 · 100 |
| Opus 5.5 `low` | 216 s | 74 · 38 · 104 s | US$1,03 | 1,00 · 1,00 · 0,95 | 102 · 33 · 61 |
| **Opus 5.5 fast mode** | **133 s** | **40 · 18 · 75 s** | US$3,14 | 1,00 · 1,00 · 1,00 | 122 · 33 · 113 |
| Sonnet 5.5 `medium` | 113 s | 33 · 26 · 53 s | US$0,42 | 1,00 · 1,00 · 0,95 | 51 · 33 · 24 |
| Haiku 5.5 `medium` | 249 s | 97 · 34 · 118 s | US$0,06 | 1,00 · 1,00 · 0,95 | 126 · 33 · 77 |

En todas las variantes la evidencia fue 100 % válida y no hubo descartes. El endpoint que se pierde en Django es `PATCH /user`. Express trae `GET /` en casi todas las variantes, que no está en la referencia de IA-0.

Lo que se ve:

- **Fast mode es la única variante que baja el tiempo sin perder nada**: 2,5 veces más rápido (de 329 a 133 s), con el mismo recall y el mismo detalle de pasos. Cuesta el doble por token: entre US$0,53 y US$1,61 por repo.
- **Sonnet 5.5 es el más rápido y 3,6 veces más barato, pero entrega menos detalle**: 51 pasos de efecto en FastAPI contra 127, y 24 en Django contra 100. El grafo queda con los endpoints, pero con menos consultas por endpoint, que son lo que alimenta la simulación.
- **`low` en Opus** baja un 34 % el tiempo, pero pierde un endpoint y el 40 % de los pasos en Django.
- **Haiku 5.5** es casi gratis y conserva el detalle en FastAPI, pero no es más rápido: sus vueltas de exploración fueron lentas (54 s en FastAPI).
- **Django rehízo la entrega en todas las variantes** (2 o 3 entregas). Corregir solo la evidencia mala (palanca 3) sigue valiendo para cualquier modelo.

Es una corrida por variante: los tiempos tienen ruido, sobre todo en paralelo. Las diferencias grandes (fast mode, el detalle de Sonnet) se repiten en los tres repos.

## Repetir

Desde la raíz, con el entorno del backend instalado y `ANTHROPIC_API_KEY` en `backend/.env`. Gasta créditos reales (~US$1,60 los tres repos con Opus):

```sh
backend/.venv/bin/python spikes/jaj-146-cache-repos/measure.py --repos fastapi express django > /tmp/jaj-146.jsonl
```

`--model` cambia el modelo, `--effort` fija el effort, `--fast` usa fast mode (solo Opus 5.5) y `--runs` repite. Cada línea es una corrida con el detalle de cada llamada al LLM (ms, tools, tokens, velocidad) y la puntuación de IA-0.
