---
status: proposed
---

# Un agente LLM extrae la estructura de los repos que el AST no cubre; los números siguen saliendo del catálogo

Enmienda el [ADR 0001](0001-el-llm-opera-sobre-el-modelo-no-lo-extrae.md), que descartó "el LLM lee el repo y escribe el modelo". El extractor por AST (`app/ingest/extract.py`) solo entiende FastAPI, y queremos analizar repos de cualquier tecnología y más de un repo por proyecto. Para esos casos, un agente con tools de solo lectura sobre el repo entrega un grafo `branchpoint.graph/v1`: componentes, conexiones, endpoints y efectos, cada uno con `archivo:línea`. El backend valida esa evidencia y `build_model.py` arma el modelo `model/v1` con el catálogo, igual que hoy.

## Qué se mantiene del ADR 0001

* **El LLM no escribe números.** El grafo no tiene latencias, costos ni tráfico. La única excepción son los valores de configuración (workers, tamaño del pool): se aceptan solo si el número aparece textualmente en la línea citada, y quedan `OBSERVADO` con esa línea como fuente.
* **El LLM no edita `model/v1`.** Entrega el grafo por la tool `submit_graph`, validada con Pydantic.
* **FastAPI sigue por AST.** Es determinista, encuentra 332 de 332 endpoints en menos de 2 s y no gasta tokens. Su salida se convierte al mismo `graph/v1`.
* **Sin IA el producto funciona** para FastAPI. Para otras tecnologías, sin key no hay extracción.

## Qué cambia

* La estructura de un repo que no es FastAPI viene de un LLM. No es reproducible: dos corridas pueden dar grafos distintos. Por eso el grafo se guarda con la ingesta y no se vuelve a extraer al abrir el proyecto.
* Cada elemento del grafo lleva `origin`: `ast`, `iac` o `llm`. La UI lo muestra, y lo que viene de `llm` queda `ESTIMADO` con fuente "LLM".
* La extracción gasta tokens: cuenta contra la cuota de la key de Branchpoint o usa la key del usuario.

## Opciones descartadas

* **Un solo prompt con el repo entero.** No cabe o cuesta demasiado en repos medianos, y no deja verificar la evidencia paso a paso.
* **Un extractor por AST para cada framework.** Es reproducible, pero es un proyecto por tecnología. No es agnóstico.
* **Que el LLM escriba `model/v1` completo.** Rompe la regla de los números.

## Consecuencias

* El contenido del repo es texto no confiable que llega al LLM. Las tools del extractor son de solo lectura, no salen de la carpeta temporal y el grafo se valida contra los archivos. Un repo no puede hacer que el agente cree versiones ni lea otro proyecto.
* El motor simula una API y una DB. Con varios servicios se simula el principal y los demás quedan como pasos `external`.
* La calidad depende del modelo. El spike [IA-0](../specs/ia-00-spike-extractor.md) la mide antes de construir el resto.
