/**
 * Live prices on demand (owner decision 2026-10-28): the top bar's Refresh fetches the current price
 * of every held and watched asset, keyless, and keeps them in a private cookie for an hour. Values,
 * P/L and share counts then use them; forecasts and actions stay from the last pipeline run.
 * - Stocks: Yahoo's chart endpoint, one request each (regular-market price, USD or CAD).
 * - Coins: CoinGecko's /coins/markets in CAD, one request, the top-ranked coin per ticker, as the
 *   pipeline's coingecko collector does (pipeline/src/advisor/collectors/coingecko.py).
 */

import { todayInToronto } from './dates'
import type { PriceBook } from './portfolio/lookup'
import { assetKey, type AssetType, type Close, type Currency } from './portfolio/types'

export const QUOTES_COOKIE = 'live_quotes'
export const QUOTES_MAX_AGE_SECONDS = 60 * 60
const REQUEST_TIMEOUT_MS = 8000
/** A CoinGecko quote not updated for a day is a dead listing (as in the pipeline). */
const MAX_COIN_QUOTE_AGE_MS = 24 * 60 * 60 * 1000
/** Polygon's MATIC trades as POL (pipeline/src/advisor/collectors/coins.py RENAMED). */
const RENAMED: Record<string, string> = { MATIC: 'POL' }
const listedAs = (symbol: string) => RENAMED[symbol] ?? symbol

export interface LiveQuote {
  price: number
  /** A stock's own currency; coins are quoted in CAD, as Wealthsimple trades them. */
  currency: Currency
  /** When the source last priced it (ISO). */
  at: string
}

export interface LiveQuotes {
  fetchedAt: string
  /** By `assetKey(assetType, symbol)`. */
  quotes: Record<string, LiveQuote>
}

export const yahooUrl = (symbol: string): string =>
  `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(symbol)}?range=1d&interval=1d`

export const coingeckoUrl = (symbols: readonly string[]): string =>
  `https://api.coingecko.com/api/v3/coins/markets?vs_currency=cad&symbols=${encodeURIComponent(
    [...new Set(symbols.map((s) => listedAs(s).toLowerCase()))].join(','),
  )}`

const isCurrency = (c: unknown): c is Currency => c === 'USD' || c === 'CAD'
const positive = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v) && v > 0

/** Yahoo's latest regular-market price, or null for anything but a positive USD or CAD price. */
export function parseYahoo(body: unknown): LiveQuote | null {
  const meta = (body as { chart?: { result?: { meta?: Record<string, unknown> }[] | null } })?.chart?.result?.[0]?.meta
  if (!meta || !positive(meta.regularMarketPrice) || !isCurrency(meta.currency)) return null
  const time = typeof meta.regularMarketTime === 'number' ? new Date(meta.regularMarketTime * 1000) : new Date()
  return { price: meta.regularMarketPrice, currency: meta.currency, at: time.toISOString() }
}

/** Each requested coin's CAD price from CoinGecko's rows: the top-ranked coin per ticker, if updated in the last day. */
export function parseCoingecko(symbols: readonly string[], rows: unknown, now: Date): Record<string, LiveQuote> {
  const rank = (r: Record<string, unknown>): [number, number] => [
    typeof r.market_cap_rank === 'number' ? 0 : 1,
    typeof r.market_cap_rank === 'number' ? r.market_cap_rank : 0,
  ]
  const best = new Map<string, Record<string, unknown>>()
  for (const row of Array.isArray(rows) ? (rows as Record<string, unknown>[]) : []) {
    const ticker = String(row.symbol ?? '').toUpperCase()
    const held = best.get(ticker)
    if (!held || rank(row) < rank(held)) best.set(ticker, row)
  }
  const out: Record<string, LiveQuote> = {}
  for (const symbol of symbols) {
    const row = best.get(listedAs(symbol))
    if (!row || !positive(row.current_price) || typeof row.last_updated !== 'string') continue
    const updated = new Date(row.last_updated)
    if (Number.isNaN(updated.getTime()) || now.getTime() - updated.getTime() > MAX_COIN_QUOTE_AGE_MS) continue
    out[symbol] = { price: row.current_price, currency: 'CAD', at: updated.toISOString() }
  }
  return out
}

export const encodeQuotes = (quotes: LiveQuotes): string => JSON.stringify(quotes)

/** The cookie's quotes, or null when missing, malformed or over an hour old; a malformed quote is dropped. */
export function decodeQuotes(text: string | undefined, now: Date): LiveQuotes | null {
  if (!text) return null
  let raw: unknown
  try {
    raw = JSON.parse(text)
  } catch {
    return null
  }
  const { fetchedAt, quotes } = (raw ?? {}) as { fetchedAt?: unknown; quotes?: unknown }
  if (typeof fetchedAt !== 'string' || Number.isNaN(Date.parse(fetchedAt))) return null
  if (now.getTime() - Date.parse(fetchedAt) > QUOTES_MAX_AGE_SECONDS * 1000) return null
  const kept: Record<string, LiveQuote> = {}
  for (const [key, q] of Object.entries((quotes ?? {}) as Record<string, Partial<LiveQuote>>)) {
    if (positive(q?.price) && isCurrency(q?.currency) && typeof q?.at === 'string') kept[key] = { price: q.price, currency: q.currency, at: q.at }
  }
  return { fetchedAt, quotes: kept }
}

/** The book with each live quote as its asset's latest close, on the quote's Toronto day. */
export function withQuotes(book: PriceBook, live: LiveQuotes | null): PriceBook {
  if (!live) return book
  const latest = new Map<string, Close>(
    Object.entries(live.quotes).map(([key, q]) => [key, { day: todayInToronto(new Date(q.at)), close: q.price, currency: q.currency }]),
  )
  return book.withLatest(latest)
}

/**
 * A price series ending at the live quote, on the quote's Toronto day. A quote in the other currency
 * (a coin's CAD quote on its USD Coinbase history) is converted at `usdCad`; without one, no change.
 */
export function withLiveClose(closes: readonly Close[], quote: LiveQuote | undefined, usdCad: number | null): readonly Close[] {
  if (!quote || closes.length === 0) return closes
  const currency = closes[closes.length - 1].currency
  const price = quote.currency === currency ? quote.price : usdCad ? (currency === 'USD' ? quote.price / usdCad : quote.price * usdCad) : null
  if (price === null) return closes
  const day = todayInToronto(new Date(quote.at))
  return [...closes.filter((c) => c.day < day), { day, close: price, currency }]
}

type Fetch = (url: string, init?: RequestInit) => Promise<Response>

async function getJson(fetchImpl: Fetch, url: string, init: RequestInit = {}): Promise<unknown | null> {
  try {
    const response = await fetchImpl(url, { ...init, signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS), cache: 'no-store' })
    return response.ok ? await response.json() : null
  } catch {
    return null // a source that doesn't answer leaves its assets on the last run's prices
  }
}

/** Live quotes for these assets, and the symbols no source priced. Never throws. */
export async function fetchQuotes(
  assets: readonly { symbol: string; assetType: AssetType }[],
  fetchImpl: Fetch = fetch,
  now: Date = new Date(),
): Promise<{ quotes: LiveQuotes; missing: string[] }> {
  const stocks = [...new Set(assets.filter((a) => a.assetType === 'stock').map((a) => a.symbol))]
  const coins = [...new Set(assets.filter((a) => a.assetType === 'crypto').map((a) => a.symbol))]
  const [stockQuotes, coinRows] = await Promise.all([
    Promise.all(
      stocks.map(async (s) => [s, parseYahoo(await getJson(fetchImpl, yahooUrl(s), { headers: { 'User-Agent': 'Mozilla/5.0 (stock-advisor)' } }))] as const),
    ),
    coins.length ? getJson(fetchImpl, coingeckoUrl(coins)) : null,
  ])
  const coinQuotes = coins.length ? parseCoingecko(coins, coinRows, now) : {}
  const quotes: Record<string, LiveQuote> = {}
  const missing: string[] = []
  for (const [s, q] of stockQuotes) {
    if (q) quotes[assetKey('stock', s)] = q
    else missing.push(s)
  }
  for (const s of coins) {
    if (coinQuotes[s]) quotes[assetKey('crypto', s)] = coinQuotes[s]
    else missing.push(s)
  }
  return { quotes: { fetchedAt: now.toISOString(), quotes }, missing }
}
