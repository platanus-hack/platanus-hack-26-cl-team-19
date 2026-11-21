-- Corrige los avisos del asesor de seguridad de Supabase sobre la migración modelo_de_datos (JAJ-56).

-- owns_project es security definer y estaba en public, así que la API la exponía como
-- /rest/v1/rpc/owns_project incluso sin login. Pasa a un esquema que la API no expone. Las
-- políticas la siguen usando, porque apuntan a la función y no a su nombre. anon y authenticated
-- necesitan usage en el esquema para evaluar esas políticas.
create schema if not exists private;
grant usage on schema private to anon, authenticated;

alter function public.owns_project(uuid) set schema private;

-- search_path vacío y nombres calificados, para que nadie pueda suplantar la tabla projects.
create or replace function private.owns_project(p uuid) returns boolean language sql stable security definer
    set search_path = '' as $$
    select exists (select 1 from public.projects where id = p and owner_id = (select auth.uid()))
$$;

-- La función del trigger no lee tablas, pero igual se fija su search_path.
alter function public.model_versions_immutable() set search_path = '';
