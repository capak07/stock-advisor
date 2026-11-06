-- Plan 6i (spec §11): a pick records whether the P floor or the model's top-N ranking chose it,
-- and, for a rank pick, its place among the forecasts ranked for that horizon. The owner reads
-- picks through the existing policy; only the pipeline writes them.
alter table picks
  add column chosen_by text not null default 'p' check (chosen_by in ('p', 'rank')),
  add column score_rank int check (score_rank > 0),
  add column score_of int check (score_of > 0),
  -- a rank pick carries both numbers and a P pick neither; a place is never past the count
  add constraint picks_rank_place check (
    (chosen_by = 'p' and score_rank is null and score_of is null)
    or (chosen_by = 'rank' and score_rank is not null and score_of is not null and score_rank <= score_of)
  );
