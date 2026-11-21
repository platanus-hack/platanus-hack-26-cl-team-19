-- Retira el secreto anterior al reemplazar la key o borrar el registro, incluso
-- si el borrado viene de la eliminación de un usuario en Supabase Auth.
create function private.cleanup_llm_credential_secret()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    delete from vault.secrets where id = old.secret_id;
    return old;
end;
$$;

revoke all on function private.cleanup_llm_credential_secret() from public, anon, authenticated;

create trigger llm_credential_secret_deleted
after delete on public.llm_credentials
for each row execute function private.cleanup_llm_credential_secret();

create trigger llm_credential_secret_replaced
after update of secret_id on public.llm_credentials
for each row when (old.secret_id is distinct from new.secret_id)
execute function private.cleanup_llm_credential_secret();
