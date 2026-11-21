-- IA-5 (JAJ-121): un proyecto puede salir de hasta 4 repos. projects.repo_connection_id sigue apuntando al
-- principal (el que simula el motor); esta tabla guarda todos, solo en los proyectos de más de un repo.
create table public.project_repositories (
    project_id          uuid not null references public.projects (id) on delete cascade,
    repo_connection_id  uuid not null references public.repo_connections (id) on delete cascade,
    branch              text not null,
    commit_sha          text,
    is_primary          boolean not null default false,
    position            smallint not null default 0,
    primary key (project_id, repo_connection_id)
);

create unique index project_repositories_one_primary on public.project_repositories (project_id) where is_primary;

-- Solo el backend (rol postgres) lee y escribe.
alter table public.project_repositories enable row level security;
revoke all on public.project_repositories from anon, authenticated;
