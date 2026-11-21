---
status: proposed
---

# El LLM opera sobre el modelo con tools tipadas; no extrae la arquitectura ni escribe números

> **Estado (2026-11-21).** Dos partes de este ADR cambiaron:
>
> * **El paso 1** lo reemplaza el [ADR 0002](0002-la-ia-lee-la-arquitectura-del-repo.md): la arquitectura la lee una IA, para cualquier framework.
> * **Dónde corre el agente:** corre en el backend, en el chat del editor, con la cuota de Branchpoint o con la key del usuario ([JAJ-94](https://linear.app/jajathom/issue/JAJ-94), [JAJ-114](https://linear.app/jajathom/issue/JAJ-114)). La CLI del usuario por MCP ([JAJ-54](https://linear.app/jajathom/issue/JAJ-54)) dejó de ser el modo principal, y la vinculación de la CLI se retiró de la interfaz ([JAJ-81](https://linear.app/jajathom/issue/JAJ-81) cancelada, [JAJ-123](https://linear.app/jajathom/issue/JAJ-123)).
>
> La regla central sigue vigente: el LLM opera con tools tipadas, no edita el JSON del modelo y no escribe números.

La extracción de la arquitectura es determinista: `extract.py` ([JAJ-7](https://linear.app/jajathom/issue/JAJ-7)) y `build_model.py` ([JAJ-45](https://linear.app/jajathom/issue/JAJ-45)) arman el modelo `branchpoint.model/v1` sin IA. El LLM aparece solo en dos lugares: (1) **clasifica los huecos** que el AST deja marcados, eligiendo valores de un enum, y (2) es un **agente de chat** que llama tools del backend para completar el escenario, simular y proponer versiones. El LLM nunca edita el JSON del modelo ni escribe un número: cada número sale del catálogo, del motor o de una frase citada del usuario. Lo decidimos así porque el AST ya encuentra 332 de 332 endpoints en menos de 2 s y es reproducible, y porque "el LLM nunca inventa números" tiene que cumplirse por construcción, no por prompt.

## Flujo

```
 repo (tarball, JAJ-53)
        │
 [1] INGESTA          determinista   extract.py → grafo + gaps[]
 [2] ENRIQUECER       LLM acotado    cada gap → clasificación de un enum + evidencia archivo:línea
 [3] ARMAR MODELO     determinista   build_model.py: grafo + catálogo + respuestas → model/v1 (versión 1)
 [4] AGENTE DE CHAT   LLM + tools    completa el escenario, simula, propone versiones
        │
     motor (simulate) → Run → editor
```

Los pasos 1 y 3 no dependen de la IA: si no hay API key, el producto igual entrega un modelo con los huecos marcados como `SUPUESTO`.

> **El paso 1 cambió con el [ADR 0002](0002-la-ia-lee-la-arquitectura-del-repo.md).** La arquitectura ya no la extrae un AST de FastAPI: la lee una IA, en la CLI del usuario o en la ingesta, con un schema estricto y para cualquier framework. Los pasos 3 y 4, y la regla de que el LLM no escribe números ni edita el modelo, siguen vigentes. El paso 2 (huecos) queda absorbido: la IA usa `shape: "unknown"` cuando no sabe.

## [2] Enriquecer huecos

`extract.py` expone una lista `gaps[]` con lo que no pudo resolver. Hoy ya los detecta, pero quedan dispersos en los efectos:

| Tipo de hueco | Ejemplo | El LLM devuelve |
|---|---|---|
| `db_shape` | `shape: unknown` (SQL en texto, pypika) | una forma del enum de JAJ-45 (`pk`, `lookup`, `range`, `count`, `count_all`, `scan`, `commit`) |
| `dynamic_target` | `plugin.instance.create(...)` | `kind` (`external`, `db`, `none`) y un nombre de destino |
| `unknown_library` | librería `emails` | `kind` (`external`, `cpu`, `none`) |

Cada clasificación trae `evidence` (archivo:línea) y queda con etiqueta `ESTIMADO`, con fuente "LLM". El número que le corresponde lo pone `build_model.py` desde el catálogo. El LLM tiene `read_file` y `grep`, con un tope de llamadas por hueco, y su respuesta se valida contra el schema. Si no la entrega o no es válida, el hueco queda como estaba.

## [4] Tools del agente

> Las mismas tools se exponen de dos formas:
>
> * **Chat del editor (modo principal):** el loop es del backend, con la cuota de Branchpoint o con la key del usuario, y aplica todo lo de abajo.
> * **`/mcp` (vía secundaria):** el loop corre en una CLI de IA conectada al servidor MCP. Se usa en pruebas internas y por quien ya trabaja con su CLI, y la interfaz no lo ofrece. Ahí no aplican el máximo de iteraciones ni la transmisión al chat. Ver Consecuencias.

Una tool es una función del backend que el LLM puede pedir ejecutar. El backend valida los argumentos, la ejecuta y le devuelve el resultado.

| Tool | Qué hace | Regla de números |
|---|---|---|
| `read_file(path, start, end)`, `grep(pattern)` | Leer el repo extraído | — |
| `get_model(version)`, `list_assumptions(version)` | Ver el modelo y sus `SUPUESTO` | — |
| `set_traffic(volume, unit, peak_factor, quote)` | "100.000 pedidos al día, ×20" → RPS de cada escenario con la fórmula de JAJ-45 | Los números vienen en `quote`, la frase del usuario; quedan `SUPUESTO` con esa fuente |
| `set_deployment(field, value, quote)` | Réplicas, vCPU, plan de DB | Igual que arriba, o un plan del catálogo de JAJ-11 |
| `set_goals(p95_ms, budget_usd_month, quote)` | Metas para evaluar las versiones | Igual que arriba |
| `propose_version(ops[], note)` | Crea una versión nueva aplicando operaciones tipadas | Cada op toma sus números del catálogo o de un `quote` |
| `simulate(version, scenario)` | Corre el motor y devuelve un resumen del `Run` | Números del motor |
| `compare(a, b, scenario)` | Mismo escenario y semilla, devuelve el delta | Números del motor |
| `estimate_cost(version)` | Costo mensual | Tabla de precios de JAJ-11 |

Las operaciones de `propose_version` son un conjunto cerrado. Para el MVP:

* `scale_api(replicas, vcpu?)`
* `change_db_plan(plan)` (plan del catálogo)
* `add_pooler()` (PgBouncer o el pooler de Supabase)
* `add_cache(endpoint, hit_ratio, quote?)`: el paso de DB queda en `on_miss`
* `move_to_queue(endpoint, step, workers)`

Si el LLM pide una op o un plan que no existe, el backend devuelve un error y el LLM tiene que corregir. Cada versión queda con origen `agente`, su antecesora y la nota ([JAJ-52](https://linear.app/jajathom/issue/JAJ-52)).

El loop tiene un máximo de iteraciones por mensaje del usuario y transmite al chat cada tool call y su resultado, para que el usuario vea qué simuló el agente.

## Opciones descartadas

* **El LLM lee el repo y escribe el modelo.** Es más lento, no es reproducible y puede inventar endpoints o latencias. El ADR 0002 acepta que la IA proponga el grafo, con evidencia y schema estricto, pero nunca el modelo ni sus números.
* **El LLM edita el JSON del modelo directamente.** No hay manera de garantizar que no invente números ni que el JSON siga siendo válido para el motor.
* **El MCP de GitHub para leer el repo.** Es una llamada por archivo y pasa por el LLM (JAJ-53). Queda descartado para la ingesta.

## Consecuencias

* Los cambios de arquitectura que el agente puede proponer son los que soportan las ops. Agregar uno nuevo es código, no prompt.
* **Dónde corre el loop.** Corre en el backend, en el chat del editor, con un máximo de iteraciones y streaming de cada tool call. La credencial es la cuota de Branchpoint o la key que el usuario guarda en Configuración (JAJ-94, JAJ-114).
  * **Historia.** [JAJ-54](https://linear.app/jajathom/issue/JAJ-54) había elegido la CLI del usuario por MCP como modo principal. El equipo lo cambió, y la vinculación de la CLI salió de la interfaz (JAJ-123).
  * **Qué queda de MCP.** `/mcp` sigue en el backend como vía secundaria, con la misma sesión de Supabase. En ese modo, Branchpoint no controla las iteraciones. Por eso mantiene un rate limit por usuario y un tope de simulaciones por día: `simulate` cuenta 1 y `compare` cuenta 2.
  * **Reglas de números.** Valen igual en los dos modos, porque se cumplen en las tools.
* El chat que pide los datos de uso ([JAJ-59](https://linear.app/jajathom/issue/JAJ-59)) se construye con `set_traffic`, `set_deployment` y `set_goals`.

## Issues

* [JAJ-66](https://linear.app/jajathom/issue/JAJ-66): exponer `gaps[]` en el extractor y clasificarlos con el LLM (paso 2).
* [JAJ-68](https://linear.app/jajathom/issue/JAJ-68): operaciones tipadas de `propose_version`.
* [JAJ-67](https://linear.app/jajathom/issue/JAJ-67): loop del agente y sus tools (paso 4), expuestas por MCP y en el chat del editor. Depende de JAJ-68 y bloquea JAJ-59.
* [JAJ-54](https://linear.app/jajathom/issue/JAJ-54): dónde corre el loop. Eligió MCP en la CLI del usuario, y ese modo pasó a ser secundario.
* [JAJ-81](https://linear.app/jajathom/issue/JAJ-81): conectar la CLI del usuario al MCP. Cancelada.
* [JAJ-94](https://linear.app/jajathom/issue/JAJ-94) y [JAJ-114](https://linear.app/jajathom/issue/JAJ-114): el chat del backend con la cuota de Branchpoint o la key del usuario (modo principal).
* [JAJ-123](https://linear.app/jajathom/issue/JAJ-123): retira el código de la vinculación con la CLI y deja `/mcp` como vía secundaria.
* [JAJ-85](https://linear.app/jajathom/issue/JAJ-85) y [JAJ-86](https://linear.app/jajathom/issue/JAJ-86): la IA lee la arquitectura para cualquier framework. Reemplazan el paso 1 (ADR 0002).
