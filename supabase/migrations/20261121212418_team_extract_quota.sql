-- IA-2 (JAJ-114): la cuota diaria de la key de Branchpoint cubre también la extracción con IA.
-- Una fila puede existir solo por una extracción, así que messages puede quedar en 0.
alter table public.team_chat_usage drop constraint team_chat_usage_messages_check;
alter table public.team_chat_usage add constraint team_chat_usage_messages_check check (messages >= 0);
alter table public.team_chat_usage alter column messages set default 0;
alter table public.team_chat_usage
    add column extractions integer not null default 0 check (extractions >= 0);

-- Con una key de OpenAI de Branchpoint, la key personal de OpenAI pasa a ser una opción como la de
-- Anthropic. Las que ya estaban guardadas se usaban siempre: siguen seleccionadas.
update public.llm_credentials set use_personal = true where provider = 'openai';
