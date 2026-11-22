-- Caché del análisis de un repo por commit (JAJ-146).
--
-- El LLM se lleva el 99 % del tiempo de una ingesta (spikes/jaj-146-cache-repos). Esta tabla guarda lo que
-- entregó (la ArchitectureSubmission ya verificada contra el repo) por repo de GitHub, commit y huella del
-- analizador. Importar de nuevo el mismo commit reutiliza la entrega y solo rearma el modelo.
--
-- No es de un usuario: la clave es el repo de GitHub y el commit. El backend resuelve el commit con el token
-- de instalación de quien importa antes de leer esta tabla; si GitHub le respondió, ese usuario puede leer el
-- commit y todo lo que hay acá sale de él.
--
-- `analyzer` es una huella del prompt, las tools y los límites del analizador (ANALYZER_FINGERPRINT en
-- backend/app/ingest/analyzer.py): si cambian, la clave cambia y el caché viejo deja de usarse.

create table repo_analyses (
    github_repo_id  bigint not null,
    commit_sha      text not null check (commit_sha ~ '^[0-9a-f]{40}$'),
    analyzer        text not null,
    provider        text,
    llm_model       text,
    submission      jsonb not null,
    usage           jsonb not null default '{}',
    steps           integer not null default 0,
    created_at      timestamptz not null default now(),
    primary key (github_repo_id, commit_sha, analyzer)
);

-- Solo el backend lee y escribe (JAJ-97): sin permisos ni políticas para anon ni authenticated.
alter table repo_analyses enable row level security;
revoke all on public.repo_analyses from anon, authenticated;
