-- Plan 2f: news items are written by every run that still sees the headline (each run reads two
-- days of feeds), so a row needs a stable key: the story item's key, one row per asset. A coin and
-- a stock can share a symbol, so rows also carry the asset type.
alter table news_items add column asset_type text not null default 'stock'
  check (asset_type in ('stock', 'crypto'));
alter table news_items alter column asset_type drop default;  -- the default only backfills old rows
alter table news_items add column story_key text;
update news_items set story_key = md5(outlet || '|' || title) where story_key is null;
alter table news_items alter column story_key set not null;
create unique index news_items_story on news_items (symbol, asset_type, story_key);
create index news_items_by_published on news_items (published_at);
