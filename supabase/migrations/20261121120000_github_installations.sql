-- Instalaciones de la GitHub App por usuario (JAJ-57). El flujo está en spikes/jaj-53-acceso-github.
--
-- Una instalación es del usuario de Branchpoint que la verificó: al volver de GitHub, el backend
-- canjea el code de OAuth y confirma con GET /user/installations que esa persona puede ver la
-- instalación. Recién entonces se guarda acá. No se guarda ningún token: el de instalación se pide
-- en cada ingesta y dura 1 hora.

create table github_installations (
    installation_id     bigint primary key,
    -- null solo con BRANCHPOINT_AUTH=off (local sin login), igual que projects.owner_id
    owner_id            uuid references auth.users (id) on delete cascade,
    account_login       text not null,         -- la cuenta u org donde se instaló, para mostrar
    created_at          timestamptz not null default now(),
    revoked_at          timestamptz            -- GitHub respondió que ya no existe (desinstalada)
);

create index github_installations_owner on github_installations (owner_id);

alter table github_installations enable row level security;
create policy own on github_installations for all
    using (owner_id = (select auth.uid())) with check (owner_id = (select auth.uid()));

-- Igual que projects: sin login (local) una conexión queda sin dueño.
alter table repo_connections alter column owner_id drop not null;

-- Una conexión por usuario y repo de GitHub: volver a analizar el mismo repo la reutiliza.
create unique index repo_connections_owner_github_repo
    on repo_connections (owner_id, github_repo_id) nulls not distinct
    where kind = 'github';
