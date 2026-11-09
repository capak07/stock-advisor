export type FeedItem = {
  kind: 'news' | 'filing' | 'insider' | 'earnings' | 'alert'
  symbol: string
  at: string
  title: string
  detail?: string
  url?: string
  important?: boolean
  /** Which kind of asset the symbol is, so a link can open a coin rather than a stock of the same symbol. */
  assetType?: 'stock' | 'crypto'
  /** A hit alert's row id, for its Dismiss button. */
  alertId?: number
  /** When the pipeline first stored a filing or insider trade: the `since` cut-off applies to this,
   * since a filing can be learned about runs after it was filed. `at` (when filed) still sorts. */
  addedAt?: string
}

export type FeedParts = {
  news: FeedItem[]
  filings: FeedItem[]
  insiders: FeedItem[]
  earnings: FeedItem[]
  alerts: FeedItem[]
}

const DAY_MS = 86_400_000
const NEWS_PER_SYMBOL = 3
const EARNINGS_DAYS = 14

const time = (item: FeedItem): number => Date.parse(item.at)

/** One "what's new" list: upcoming earnings (next 14 days, soonest first), then everything since
 * `since` newest first, with at most 3 news items per symbol. Filings and insider trades count from
 * when they were stored (`addedAt`, else `at`). */
export const buildFeed = (parts: FeedParts, opts: { since: string; now: string }): FeedItem[] => {
  const since = Date.parse(opts.since)
  const now = Date.parse(opts.now)

  const upcoming = parts.earnings
    .filter((e) => time(e) >= now && time(e) <= now + EARNINGS_DAYS * DAY_MS)
    .sort((a, b) => time(a) - time(b))

  const seen = new Map<string, number>()
  const news = [...parts.news]
    .filter((n) => time(n) >= since)
    .sort((a, b) => time(b) - time(a))
    .filter((n) => {
      const count = (seen.get(n.symbol) ?? 0) + 1
      seen.set(n.symbol, count)
      return count <= NEWS_PER_SYMBOL
    })

  // a hit alert stays until the owner dismisses it, so `since` does not cut it
  const rest = [...news, ...[...parts.filings, ...parts.insiders].filter((i) => Date.parse(i.addedAt ?? i.at) >= since), ...parts.alerts]
    .sort((a, b) => time(b) - time(a))

  return [...upcoming, ...rest]
}
