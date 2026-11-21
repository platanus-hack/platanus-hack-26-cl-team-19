# IA-0: Medir el analizador con LLM reales

**Área:** backend · **Depende de:** la rama de la PR #59 (`gonzalomatus/feat/jaj-85-86-arquitectura-ia`), no hace falta que esté mergeada · **Tamaño:** S (medio día) · **Informa a:** IA-4

## Pregunta

El agente es el único camino para importar un repo. ¿`analyze_repo` entrega una arquitectura correcta, en un tiempo y a un costo aceptables, con un LLM real?

La PR #59 lo probó por CLI sobre un repo Express. El analizador del servidor solo tiene tests con un LLM falso.

## Qué hacer

Un script en `spikes/ia-0-analizador/` que importa desde `backend/`:

```python
from app.ingest.analyzer import analyze_repo
from app.agent.loop import AnthropicLLM
from app.agent.openai_llm import OpenAILLM
```

1. Clonar cada repo en una carpeta temporal y llamar `analyze_repo(root, llm, repo_name)`.
2. Registrar por corrida: endpoints entregados, componentes, vueltas, tokens (el `usage` que devuelve), segundos y si terminó con `AnalysisFailed`.
3. Calcular el costo con `cost_usd` de `app/agent/loop.py`. Si el modelo no está en `app/costs/prices/manual.json`, reportar solo tokens.
4. Repos:

   | Repo | Para qué |
   |---|---|
   | `fastapi-realworld-example-app` | Hay referencia: 19 endpoints en `backend/app/samples/`. Es lo que antes resolvía el AST. |
   | `full-stack-fastapi-template` | Referencia en `backend/tests/fixtures/`. |
   | Un repo Node (Express o NestJS) con Docker Compose | Otro lenguaje, con infraestructura declarada. |
   | Un repo Django, Go o Rails | Tercer lenguaje. |
   | Un repo grande (más de 150 endpoints) | El schema acepta 300 endpoints y el loop 40 vueltas: ver si alcanza. |

5. Para los repos sin referencia, contar los endpoints a mano (con `grep` de las rutas) para tener el denominador.
6. Correr cada repo dos veces con cada proveedor, para ver cuánto cambia el resultado.
7. Revisar a mano 20 pasos al azar por repo: ¿el `archivo:línea` existe y el `shape` calza con el código?

El gasto en tokens es real. Antes de correr la matriz completa, correr un repo y estimar el total.

## Qué medir

| Medida | Umbral propuesto |
|---|---|
| Endpoints encontrados / endpoints reales | ≥ 80 % |
| Endpoints inventados (no existen en el repo) | 0 |
| Evidencia válida en la muestra (el archivo existe y la línea corresponde) | ≥ 95 % |
| `shape` correcto en la muestra | ≥ 80 % |
| Tiempo total por repo | < 3 min |
| Costo por repo | < US$ 1 |
| Corridas que terminan en `AnalysisFailed` | 0 en repos de hasta 50 endpoints |
| Componentes del Compose detectados | todos |

## Entregable

`spikes/ia-0-analizador/README.md` con la tabla de resultados por repo y proveedor, y una lista concreta de ajustes para IA-4: cambios al prompt `SYSTEM`, a `MAX_ITERATIONS`, `MAX_LINES` y `MAX_TREE`, y el tope de tokens que conviene poner a la key de Branchpoint.

Conclusión en una línea: **listo para producción**, **listo con los ajustes de IA-4** o **no alcanza** (y para qué tamaño de repo sí).

## Fuera de alcance

* Cambiar `analyzer.py`. Los ajustes van en IA-4.
* La cuota y la UI.
