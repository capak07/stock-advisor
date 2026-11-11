-- The day-trader skill's top 3 at the open, frozen when each signal is first stored.
-- RLS and grants on daytrade_signals already cover the new column.
alter table daytrade_signals
  add column skill_rank int check (skill_rank between 1 and 3);

create unique index daytrade_signals_skill_rank on daytrade_signals (day, skill_rank)
  where skill_rank is not null;
