-- The owner's marginal tax rate (combined federal and provincial, in percent), for the after-tax results on History.
-- Nullable: until it is set, History shows no after-tax figure for a taxable account. The new column inherits the
-- settings table's owner_update and pipeline_read policies.
alter table settings
  add column marginal_tax_pct numeric check (marginal_tax_pct between 0 and 100);
