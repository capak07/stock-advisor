-- Exit plan for holdings: each holding's action carries its exit plan (a jsonb document built from
-- simulated price paths), and each graded outcome records whether the plan's prices were reached.
-- All nullable: rows from before this migration have no plan and no touch results.
alter table holding_actions add column exit_plan jsonb;

alter table holding_action_outcomes
  add column touched_sell_at boolean,
  add column touched_breakeven boolean,
  add column max_close numeric check (max_close > 0);
