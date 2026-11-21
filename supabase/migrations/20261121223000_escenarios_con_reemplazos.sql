-- Reemplazos de un escenario del proyecto (JAJ-131): lo que cambia la situación, no la arquitectura.
--
-- Un escenario guardaba solo su tasa (multiplier o rps). Ahora también puede traer, en un jsonb:
--   * endpoint_weights: la mezcla de endpoints ({"POST /checkout": 3});
--   * slowdowns: dependencias más lentas por nodo del grafo ({"external:pagos": 10, "db": 1.5});
--   * business: conversión y ticket promedio para el costo de fallar ({"conversion": 0.03}).
-- Se aplican al simular o comparar cualquier versión con ese escenario, sin crear versiones. La forma
-- la valida la API (RunParams y ScenarioIn en backend/app/api/schemas.py).
--
-- Es una columna, no una tabla: no hace falta otro revoke. La tabla ya solo la escribe el backend
-- (JAJ-97) y authenticated sigue leyendo sus propias filas con read_own.

alter table public.scenarios add column overrides jsonb;
