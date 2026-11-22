-- JAJ-142: salto discreto de tráfico en escenarios guardados.
-- Una columna separada permite que un backend anterior siga leyendo el escenario con su tasa base.
alter table public.scenarios add column traffic_step jsonb;
