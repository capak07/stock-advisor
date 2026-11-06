-- Plan 6i (spec §11): a pick records whether the P floor or the model's top-N ranking chose it,
-- and, for a rank pick, its place among the forecasts ranked for that horizon. The owner reads
-- picks through the existing policy; only the pipeline writes them.
alter table picks
  add column chosen_by text not null default 'p' check (chosen_by in ('p', 'rank')),
  add column score_rank int check (score_rank > 0),
  add column score_of int check (score_of > 0);
