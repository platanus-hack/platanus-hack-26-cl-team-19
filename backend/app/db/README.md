# `app/db`: persistencia

Todavía no hay código aquí. Esta carpeta es para guardar lo que el producto necesita recordar entre sesiones:

- **Project:** el repo conectado.
- **ModelVersion:** cada versión del modelo de arquitectura (`branchpoint.model/v1`).
- **Scenario:** escenarios de tráfico.
- **Run:** resultados de simulación (`branchpoint.run/v1`).

Corresponde a la tarjeta JAJ-17 (Supabase), que se recrea cuando cierre M1.

El motor (`app/engine`) no depende de esta carpeta: recibe un modelo y devuelve un `Run`, sin guardar nada.
