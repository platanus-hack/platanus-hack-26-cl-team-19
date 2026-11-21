-- IA-6 (JAJ-115): imágenes y logs que el usuario sube al chat. Son temporales: vencen en
-- expires_at y el backend los borra (objeto y fila) en la siguiente llamada de ese usuario.
create table public.chat_attachments (
    id            uuid primary key default gen_random_uuid(),
    owner_id      uuid not null references auth.users (id) on delete cascade,
    project_id    uuid not null references public.projects (id) on delete cascade,
    kind          text not null check (kind in ('image', 'log')),
    filename      text not null,
    media_type    text not null,
    bytes         bigint check (bytes >= 0),
    storage_path  text not null unique,
    status        text not null default 'pending' check (status in ('pending', 'ready')),
    created_at    timestamptz not null default now(),
    expires_at    timestamptz not null
);

create index chat_attachments_project_idx on public.chat_attachments (project_id, owner_id, expires_at);
create index chat_attachments_expires_idx on public.chat_attachments (expires_at);

-- Solo el backend (rol postgres) lee y escribe, como team_chat_usage.
alter table public.chat_attachments enable row level security;
revoke all on public.chat_attachments from anon, authenticated;

-- Bucket privado, sin políticas para anon ni authenticated: entra el backend con la secret key y el
-- navegador con una URL firmada. El esquema storage lo crea el servicio de Storage; con solo
-- `supabase db start` (el CI) no existe y el bucket se omite.
do $$
begin
    if to_regclass('storage.buckets') is not null then
        insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
        values (
            'chat-attachments', 'chat-attachments', false, 10485760,
            array['image/png', 'image/jpeg', 'image/webp', 'image/gif',
                  'text/plain', 'text/csv', 'application/json', 'application/x-ndjson']
        )
        on conflict (id) do nothing;
    end if;
end
$$;
