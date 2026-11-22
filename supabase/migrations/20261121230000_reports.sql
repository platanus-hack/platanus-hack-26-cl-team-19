-- JAJ-127: reportes de simulación. Cada corrida guarda su reporte como una foto congelada
-- (branchpoint.report/v1): el PDF y el Markdown salen de body, así que nunca hay que volver a simular
-- y el reporte no cambia aunque después se editen la versión o los precios. Una comparación es otro
-- reporte (kind = 'comparison') que se arma con dos reportes ya guardados.
create table public.reports (
    id              uuid primary key,
    project_id      uuid not null references public.projects (id) on delete cascade,
    kind            text not null check (kind in ('run', 'comparison')),
    -- resumen para listar sin leer body (en una comparación, los de B)
    version_number  integer,
    scenario        text,
    rps             numeric,
    seed            integer,
    p95_ms          numeric,
    error_rate      numeric,
    usd_month       numeric,
    body            jsonb not null,
    created_at      timestamptz not null default now(),
    constraint reports_body_schema check (body ->> 'schema' = 'branchpoint.report/v1')
);

create index reports_project_idx on public.reports (project_id, created_at desc);

-- Solo el backend (rol postgres) lee y escribe, como las demás tablas desde JAJ-97.
alter table public.reports enable row level security;
revoke all on public.reports from anon, authenticated;
