alter table public.model_versions add column proposal_id uuid;

create unique index model_versions_project_proposal_key
  on public.model_versions (project_id, proposal_id)
  where proposal_id is not null;
