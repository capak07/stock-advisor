-- Low model rank (spec 2026-11-15): each run, every US stock the screener scored, with its percentile
-- among them (0 = lowest score) and whether it is in the bottom tenth. The owner reads; only the
-- pipeline writes. The pipeline keeps the latest runs' rows only.
create table screen_ranks (
  run_id bigint not null references runs (id) on delete cascade,
  symbol text not null,
  market text not null check (market in ('US', 'TSX')),
  pct double precision not null check (pct > 0 and pct <= 1),
  low boolean not null,
  scored int not null check (scored > 0),
  primary key (run_id, symbol)
);
create index screen_ranks_by_symbol on screen_ranks (symbol, run_id desc);

alter table screen_ranks enable row level security;
create policy owner_read on screen_ranks for select to authenticated using ((select public.is_owner()));
create policy pipeline_write on screen_ranks for all to pipeline_rw using (true) with check (true);
grant select, insert, update, delete on screen_ranks to pipeline_rw;
