-- Las cuentas que ya usaban una clave propia conservan esa opción.
alter table public.llm_credentials add column use_personal boolean not null default true;
alter table public.llm_credentials alter column use_personal set default false;

create table public.team_chat_usage (
    owner_id uuid not null references auth.users(id) on delete cascade,
    usage_date date not null,
    messages integer not null check (messages > 0),
    primary key (owner_id, usage_date)
);

alter table public.team_chat_usage enable row level security;
revoke all on public.team_chat_usage from anon, authenticated;
