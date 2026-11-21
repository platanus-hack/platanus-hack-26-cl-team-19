---
status: proposed
---

# La IA lee la arquitectura del repo, para cualquier framework; los números siguen sin salir del LLM

Reemplaza el paso 1 del [ADR 0001](0001-el-llm-opera-sobre-el-modelo-no-lo-extrae.md), que era un extractor AST determinista. Ese extractor solo leía FastAPI, y no queremos código específico por framework ([JAJ-85](https://linear.app/jajathom/issue/JAJ-85), [JAJ-86](https://linear.app/jajathom/issue/JAJ-86)).

Ahora la arquitectura (endpoints → pasos con forma de query, caché, colas, servicios externos y componentes) la lee una IA. Lo hace con un schema estricto, igual para todos los lenguajes. La IA puede correr en dos lugares, con el mismo schema:

* **La CLI del usuario** (modo MCP, [JAJ-54](https://linear.app/jajathom/issue/JAJ-54)): lee su repo local y llama a `submit_architecture`.
* **La ingesta de GitHub:** Claude corre en el backend y lee el tarball con `list_files`, `read_file` y `grep` (`backend/app/ingest/analyzer.py`). Usa la API key del usuario o, en modo demo, la del equipo.

Lo demás del ADR 0001 sigue igual: el modelo lo arma `build_model.py` con el catálogo, el LLM no edita el JSON del modelo, y el agente opera con tools tipadas.

## Reglas

* **La IA clasifica; los números salen del catálogo.** `kind`, `op` y `shape` son enums del catálogo (`pk`, `lookup`, `range`, `scan`, `commit`...). El schema no tiene campos de tiempo, filas ni costo.
* **La configuración se cita, no se inventa.** Los únicos números que acepta son configuración escrita en el repo, en `observations`: los workers de la API y el pool de conexiones. Cada uno va con su `archivo:línea`.
  * **En la ingesta:** el servidor revisa que el número esté en esa línea. Si está, queda `OBSERVADO`; si no, se descarta con un aviso.
  * **Desde la CLI:** el servidor no ve el archivo, así que queda `ESTIMADO` y por revisar.
* **Evidencia y procedencia.** Cada endpoint, paso y componente trae `archivo:línea`, `why` y `origin` (`kind: "ia"`, `via: "cli" | "ingesta"`). Los tiempos de los pasos son `ESTIMADO` como máximo.
* **CPU base.** La CPU del framework queda `SUPUESTO` si el framework no es en el que la midió el catálogo (FastAPI, JAJ-43 y JAJ-46).
* **La IaC manda.** `iac.py` sigue siendo determinista y no depende del framework, porque lee archivos de despliegue y no código. Si declara un servicio o los workers, gana sobre lo que propone la IA.
* **Validación con corrección.** Si la propuesta no pasa el schema, el error vuelve a la IA para que la corrija.

## Opciones descartadas

* **Extractores deterministas por lenguaje** (AST o tree-sitter por framework). Cada framework es código nuevo y mantenimiento. El de FastAPI ya tenía unas 1.100 líneas.
* **La IA como respaldo del extractor de FastAPI.** Mantenía dos caminos y dejaba FastAPI con privilegios.
* **Herramientas existentes.** [OWASP Noir](https://github.com/owasp-noir/noir) encuentra endpoints en más de 50 frameworks, pero no los accesos a la DB ni su forma. CodeBoarding y stakgraph arman diagramas de módulos. Ninguna entrega lo que necesita el motor.
* **La IA escribe el modelo o sus tiempos.** Sigue descartado, como en el ADR 0001.

## Consecuencias

* **Reproducibilidad.** Dos análisis del mismo commit pueden diferir. Cada versión guarda su procedencia, y el usuario puede volver a mandar la arquitectura (`submit_architecture` con `project_id`).
* **Costo.** La ingesta desde la web gasta tokens: los de la key del usuario o los de la credencial del equipo. En modo demo hay un tope de 5 análisis por usuario y por día, y el modelo guarda los tokens usados en `repo.source.analysis`.
* **Credencial obligatoria.** Sin la key del usuario y sin modo demo, la importación desde GitHub responde 422 y sugiere la CLI.
* **Modelos de ejemplo.** `backend/app/samples/` queda como datos fijos generados por el extractor antiguo, para la demo y los tests del motor.
