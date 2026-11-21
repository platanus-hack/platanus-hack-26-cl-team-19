-- Solo el backend escribe en las tablas de Branchpoint (JAJ-97).
--
-- El backend entra con DATABASE_URL, un rol que se salta RLS, y filtra por owner_id. El frontend
-- usa Supabase solo para el login: no lee ni escribe tablas con supabase-js. Pero Supabase les da
-- a anon y authenticated todos los permisos sobre cada tabla nueva de public, y varias políticas
-- dejaban escribir. Con la key pública y su propio token, un usuario podía, por PostgREST:
--
--   * insertar en github_installations una instalación ajena (los ids son correlativos) y el
--     backend la tomaba como verificada: listaba y analizaba esos repos (BE-02);
--   * insertar en runs un resultado falso con el cache_key que quisiera (BE-15).
--
-- Desde acá:
--   * anon no tiene ningún permiso sobre estas tablas;
--   * authenticated solo puede leer, y las políticas le muestran solo lo suyo (la segunda barrera
--     si algún día el frontend lee con supabase-js);
--   * toda escritura pasa por el backend, que valida.
--
-- Una tabla nueva en public vuelve a nacer con todos los permisos (los default privileges de
-- Supabase). El test tests/db/test_permissions.py falla si alguna tabla le da escritura a anon o
-- authenticated, así que la próxima migración tiene que hacer el mismo revoke.

-- ---------------------------------------------------------------------------------------------
-- Permisos
-- ---------------------------------------------------------------------------------------------

revoke all on
    public.repo_connections, public.github_installations, public.projects, public.usage_profiles,
    public.model_versions, public.ingestions, public.scenarios, public.runs, public.chat_sessions,
    public.chat_messages, public.llm_credentials
from anon;

revoke insert, update, delete, truncate, references, trigger on
    public.repo_connections, public.github_installations, public.projects, public.usage_profiles,
    public.model_versions, public.ingestions, public.scenarios, public.runs, public.chat_sessions,
    public.chat_messages, public.llm_credentials
from authenticated;

-- llm_credentials guarda el id del secreto en Vault: solo el backend lo lee (no tiene políticas).
revoke select on public.llm_credentials from authenticated;

-- ---------------------------------------------------------------------------------------------
-- Políticas: de "todo lo mío" a "leer lo mío"
-- ---------------------------------------------------------------------------------------------

drop policy own on public.repo_connections;
create policy read_own on public.repo_connections for select using (owner_id = (select auth.uid()));

drop policy own on public.github_installations;
create policy read_own on public.github_installations for select using (owner_id = (select auth.uid()));

drop policy own on public.projects;
create policy read_own on public.projects for select using (owner_id = (select auth.uid()));

drop policy own on public.usage_profiles;
create policy read_own on public.usage_profiles for select using (private.owns_project(project_id));

drop policy insert_own on public.model_versions;  -- queda read_own

drop policy own on public.scenarios;
create policy read_own on public.scenarios for select using (private.owns_project(project_id));

drop policy insert_own on public.runs;  -- queda read_own

drop policy own on public.chat_sessions;
create policy read_own on public.chat_sessions for select using (private.owns_project(project_id));

drop policy own on public.chat_messages;
create policy read_own on public.chat_messages for select
    using (exists (select 1 from public.chat_sessions s where s.id = session_id and private.owns_project(s.project_id)));
