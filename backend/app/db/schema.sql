-- Modelo de datos persistente de Branchpoint (JAJ-55).
--
-- Es la propuesta original que documenta README.md. No se aplica: JAJ-56 la copió a
-- supabase/migrations/, que es la fuente de verdad del esquema. Un cambio al esquema es una
-- migración nueva allá (ver docs/supabase-local.md), no una edición de este archivo.

-- ---------------------------------------------------------------------------------------------
-- Tipos
-- ---------------------------------------------------------------------------------------------

create type source_kind as enum ('github', 'zip');
create type version_origin as enum ('repo', 'manual', 'agente');
create type ingestion_status as enum ('queued', 'running', 'done', 'failed');
create type chat_role as enum ('user', 'assistant', 'tool');

-- ---------------------------------------------------------------------------------------------
-- De dónde sale el código
-- ---------------------------------------------------------------------------------------------

-- Un repo de GitHub conectado o un .zip subido. Es del usuario, no del proyecto: el mismo repo
-- puede alimentar varios proyectos (por ejemplo, uno por rama).
create table repo_connections (
    id                      uuid primary key default gen_random_uuid(),
    owner_id                uuid not null references auth.users (id) on delete cascade,
    kind                    source_kind not null,
    -- github: la instalación de la GitHub App y el repo. Nunca un token (ver README).
    github_installation_id  bigint,
    github_repo_id          bigint,
    repo_full_name          text,              -- "owner/nombre", para mostrar
    default_branch          text,
    token_secret_id         uuid,              -- solo si JAJ-53 elige OAuth: id en Supabase Vault
    -- zip: dónde quedó en Storage y su huella. storage_path pasa a null al borrar el archivo.
    storage_path            text,
    archive_sha256          text,
    archive_bytes           bigint,
    created_at              timestamptz not null default now(),
    revoked_at              timestamptz,       -- el usuario desinstaló la app o revocó el acceso
    constraint repo_connections_github check (
        kind <> 'github' or (github_installation_id is not null and repo_full_name is not null)
    ),
    constraint repo_connections_zip check (kind <> 'zip' or archive_sha256 is not null)
);

create index repo_connections_owner on repo_connections (owner_id);

-- ---------------------------------------------------------------------------------------------
-- Proyectos y sus metas
-- ---------------------------------------------------------------------------------------------

-- Un repo analizado (o un modelo de ejemplo) con sus metas. Es lo que abre el editor.
create table projects (
    id                  uuid primary key default gen_random_uuid(),
    -- null mientras no haya login (la API de JAJ-52 todavía no tiene auth)
    owner_id            uuid references auth.users (id) on delete cascade,
    name                text not null,
    repo_connection_id  uuid references repo_connections (id) on delete set null,
    branch              text,                  -- rama que se analiza; la de la v1
    sample_id           text,                  -- id de GET /models si salió de un ejemplo
    -- metas que declara el usuario: con ellas el agente elige entre alternativas
    slo_p95_ms          numeric check (slo_p95_ms > 0),
    slo_error_rate      numeric check (slo_error_rate between 0 and 1),
    budget_usd_month    numeric check (budget_usd_month >= 0),
    -- contador para numerar versiones sin carreras (ver add_version en el README)
    version_count       integer not null default 0,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now()
);

create index projects_owner on projects (owner_id, created_at desc);

-- Lo que el usuario declara sobre su sistema: tráfico, despliegue y negocio (las 3 preguntas de
-- JAJ-45), dichas en el chat (JAJ-59), en el formulario o leídas de IaC (JAJ-60). Solo se agrega:
-- el perfil vigente es el último, y cada versión del modelo apunta al que usó.
create table usage_profiles (
    id                  uuid primary key default gen_random_uuid(),
    project_id          uuid not null references projects (id) on delete cascade,
    -- cada número en el formato de JAJ-45: {"value", "unit", "label", "source", "date"}
    -- ej. {"traffic": {"orders_per_day": {...}, "cyberday_multiplier": {...}},
    --      "deployment": {"db_plan": {...}, "api_replicas": {...}},
    --      "business": {"ticket_usd": {...}, "conversion": {...}}}
    answers             jsonb not null,
    source_message_id   uuid,                  -- mensaje del chat donde se dijo (FK más abajo)
    created_at          timestamptz not null default now(),
    constraint usage_profiles_answers_object check (jsonb_typeof(answers) = 'object')
);

create index usage_profiles_project on usage_profiles (project_id, created_at desc);

-- ---------------------------------------------------------------------------------------------
-- Versiones del modelo (como commits)
-- ---------------------------------------------------------------------------------------------

-- Cada versión es inmutable: editar es crear otra con parent_number. number es v1, v2... dentro
-- del proyecto, y la FK compuesta obliga a que la antecesora sea del mismo proyecto.
create table model_versions (
    id                  uuid primary key default gen_random_uuid(),
    project_id          uuid not null references projects (id) on delete cascade,
    number              integer not null check (number >= 1),
    parent_number       integer,
    origin              version_origin not null,
    note                text check (char_length(note) <= 500),
    model               jsonb not null,        -- branchpoint.model/v1 completo
    model_schema        text not null default 'branchpoint.model/v1',
    -- qué produjo esta versión
    commit_sha          text,                  -- origin = repo: el commit analizado
    usage_profile_id    uuid references usage_profiles (id) on delete set null,
    source_message_id   uuid,                  -- origin = agente: la propuesta aplicada (FK más abajo)
    created_by          uuid references auth.users (id) on delete set null,
    created_at          timestamptz not null default now(),
    unique (project_id, number),
    foreign key (project_id, parent_number) references model_versions (project_id, number),
    constraint model_versions_v1_has_no_parent check ((number = 1) = (parent_number is null)),
    constraint model_versions_parent_before check (parent_number < number),
    constraint model_versions_schema check (model ->> 'schema' = model_schema)
);

-- Los modelos no se editan: un cambio es una versión nueva.
create function model_versions_immutable() returns trigger language plpgsql as $$
begin
    raise exception 'La v% no se edita: guarda el cambio como una versión nueva', old.number;
end $$;

create trigger model_versions_no_update before update on model_versions
    for each row execute function model_versions_immutable();

-- ---------------------------------------------------------------------------------------------
-- Ingesta: el progreso que muestra "Conectar repo" (acceso, análisis, preparación)
-- ---------------------------------------------------------------------------------------------

create table ingestions (
    id                  uuid primary key default gen_random_uuid(),
    project_id          uuid not null references projects (id) on delete cascade,
    repo_connection_id  uuid references repo_connections (id) on delete set null,
    branch              text,
    commit_sha          text,
    status              ingestion_status not null default 'queued',
    stage               text,                  -- acceso | analisis | preparacion
    stats               jsonb,                 -- repo.stats del extractor (endpoints, riesgos...)
    error_code          text,
    error_message       text,                  -- en español, para mostrarlo tal cual
    model_version_id    uuid references model_versions (id) on delete set null,
    started_at          timestamptz,
    finished_at         timestamptz,
    created_at          timestamptz not null default now(),
    constraint ingestions_done_has_version check (status <> 'done' or model_version_id is not null),
    constraint ingestions_failed_has_error check (status <> 'failed' or error_message is not null)
);

create index ingestions_project on ingestions (project_id, created_at desc);

-- ---------------------------------------------------------------------------------------------
-- Escenarios y runs
-- ---------------------------------------------------------------------------------------------

-- Escenarios del proyecto, no de una versión: así se compara cualquier par de versiones con el
-- mismo escenario. La tasa sale de rps fijo o de multiplier × el pico del modelo de cada versión.
create table scenarios (
    id                  uuid primary key default gen_random_uuid(),
    project_id          uuid not null references projects (id) on delete cascade,
    name                text not null,         -- pico_normal, cyberday, ...
    description         text,                  -- la situación en texto plano del usuario
    multiplier          numeric check (multiplier > 0),
    rps                 numeric check (rps > 0),
    duration_s          numeric not null default 60 check (duration_s > 0 and duration_s <= 3600),
    arrivals            text not null default 'poisson' check (arrivals in ('poisson', 'uniform')),
    client_timeout_s    numeric default 30 check (client_timeout_s > 0),
    cache_hit_ratio     numeric check (cache_hit_ratio between 0 and 1),
    failures            jsonb not null default '[]',  -- DB lenta, caída de caché... (motor futuro)
    source_message_id   uuid,                  -- si lo armó el agente desde el chat (FK más abajo)
    created_at          timestamptz not null default now(),
    unique (project_id, name),
    constraint scenarios_one_rate check ((multiplier is null) <> (rps is null))
);

-- Un run es reproducible: misma versión + mismos parámetros + misma semilla + mismo motor dan el
-- mismo resultado. cache_key junta todo eso, así simular dos veces lo mismo no repite el cálculo.
create table runs (
    id                  uuid primary key default gen_random_uuid(),
    project_id          uuid not null references projects (id) on delete cascade,
    model_version_id    uuid not null references model_versions (id) on delete cascade,
    scenario_id         uuid references scenarios (id) on delete set null,
    scenario_name       text not null,         -- queda aunque se borre el escenario
    seed                integer not null,
    params              jsonb not null,        -- RunParams resueltos (rps final incluido)
    engine_version      text not null,         -- versión del backend: el motor cambia (JAJ-43, JAJ-48)
    cache_key           text not null unique,  -- sha256(model_version_id, params, seed, engine_version)
    result              jsonb not null,        -- branchpoint.run/v1 completo, con la serie por segundo
    -- resumen para listar y comparar sin leer result
    p95_ms              numeric,
    error_rate          numeric not null,
    throughput_rps      numeric not null,
    bottleneck_resource text,
    elapsed_ms          numeric,
    created_at          timestamptz not null default now(),
    constraint runs_result_schema check (result ->> 'schema' = 'branchpoint.run/v1')
);

create index runs_version on runs (model_version_id, created_at desc);

-- ---------------------------------------------------------------------------------------------
-- Chat con el agente
-- ---------------------------------------------------------------------------------------------

create table chat_sessions (
    id                  uuid primary key default gen_random_uuid(),
    project_id          uuid not null references projects (id) on delete cascade,
    title               text,
    created_at          timestamptz not null default now()
);

-- content guarda los bloques tal cual los muestra el panel: texto, llamadas a herramientas con su
-- input y resultado, y propuestas (modelo propuesto + run simulado). El costo es para BYOS (JAJ-54).
create table chat_messages (
    id                  uuid primary key default gen_random_uuid(),
    session_id          uuid not null references chat_sessions (id) on delete cascade,
    role                chat_role not null,
    content             jsonb not null,
    llm_provider        text,                  -- solo en mensajes del asistente
    llm_model           text,
    input_tokens        integer,
    output_tokens       integer,
    cost_usd            numeric,               -- calculado con la tabla de precios, nunca por el LLM
    created_at          timestamptz not null default now()
);

create index chat_messages_session on chat_messages (session_id, created_at);

alter table usage_profiles
    add foreign key (source_message_id) references chat_messages (id) on delete set null;
alter table model_versions
    add foreign key (source_message_id) references chat_messages (id) on delete set null;
alter table scenarios
    add foreign key (source_message_id) references chat_messages (id) on delete set null;

-- ---------------------------------------------------------------------------------------------
-- Credenciales de IA (solo si JAJ-54 decide guardarlas en el servidor)
-- ---------------------------------------------------------------------------------------------

-- La key nunca está en esta tabla: vive cifrada en Supabase Vault y aquí queda su id.
create table llm_credentials (
    id                  uuid primary key default gen_random_uuid(),
    owner_id            uuid not null references auth.users (id) on delete cascade,
    provider            text not null,         -- anthropic, openai, ...
    secret_id           uuid not null,         -- vault.secrets.id
    key_hint            text,                  -- últimos 4 caracteres, para reconocerla
    created_at          timestamptz not null default now(),
    revoked_at          timestamptz,
    unique (owner_id, provider)
);

-- ---------------------------------------------------------------------------------------------
-- Row Level Security: cada usuario ve solo lo suyo
-- ---------------------------------------------------------------------------------------------
-- El backend se conecta con DATABASE_URL (rol con BYPASSRLS) y filtra por owner_id. Las políticas
-- son la segunda barrera si el frontend lee con supabase-js. Los proyectos sin dueño (sin login)
-- solo los ve el backend.

alter table repo_connections enable row level security;
alter table projects enable row level security;
alter table usage_profiles enable row level security;
alter table model_versions enable row level security;
alter table ingestions enable row level security;
alter table scenarios enable row level security;
alter table runs enable row level security;
alter table chat_sessions enable row level security;
alter table chat_messages enable row level security;
alter table llm_credentials enable row level security;

create function owns_project(p uuid) returns boolean language sql stable security definer
    set search_path = public as $$
    select exists (select 1 from projects where id = p and owner_id = auth.uid())
$$;

create policy own on repo_connections for all using (owner_id = auth.uid()) with check (owner_id = auth.uid());
create policy own on projects for all using (owner_id = auth.uid()) with check (owner_id = auth.uid());
create policy own on usage_profiles for all using (owns_project(project_id)) with check (owns_project(project_id));
-- versiones y runs: leer e insertar, nunca editar
create policy read_own on model_versions for select using (owns_project(project_id));
create policy insert_own on model_versions for insert with check (owns_project(project_id));
create policy own on ingestions for select using (owns_project(project_id));
create policy own on scenarios for all using (owns_project(project_id)) with check (owns_project(project_id));
create policy read_own on runs for select using (owns_project(project_id));
create policy insert_own on runs for insert with check (owns_project(project_id));
create policy own on chat_sessions for all using (owns_project(project_id)) with check (owns_project(project_id));
create policy own on chat_messages for all
    using (exists (select 1 from chat_sessions s where s.id = session_id and owns_project(s.project_id)))
    with check (exists (select 1 from chat_sessions s where s.id = session_id and owns_project(s.project_id)));
-- llm_credentials: sin políticas para el usuario; solo el backend lee el secret_id
