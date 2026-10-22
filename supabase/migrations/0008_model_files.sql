-- Plan 3b: each trained stock model's files (gzip-compressed LightGBM text, calibration and
-- metadata), kept beside its `models` row (owner's decision, 2026-10-21: Postgres rather than
-- Storage or the Actions cache, so no new secret). About 6 MB a market; the weekly job keeps the
-- active model and one other per kind.
create table model_files (
  version text not null references models (version) on delete cascade,
  name text not null check (name ~ '^[a-z0-9_]{1,40}$'),
  body bytea not null,
  primary key (version, name)
);

alter table model_files enable row level security;
create policy owner_read on model_files for select to authenticated using ((select public.is_owner()));
create policy pipeline_write on model_files for all to pipeline_rw using (true) with check (true);
grant select, insert, update, delete on model_files to pipeline_rw;
