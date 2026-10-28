import { describe, expect, it } from 'vitest'
import { PriceBook } from './portfolio/lookup'
import {
  QUOTES_MAX_AGE_SECONDS,
  coingeckoUrl,
  decodeQuotes,
  encodeQuotes,
  fetchQuotes,
  parseCoingecko,
  parseYahoo,
  withLiveClose,
  withQuotes,
  yahooUrl,
  type LiveQuotes,
} from './quotes'

const NOW = new Date('2026-10-28T18:14:00Z') // 2:14 PM in Toronto

const yahoo = (price: unknown, currency = 'USD', time = 1793131200) => ({
  chart: { result: [{ meta: { currency, regularMarketPrice: price, regularMarketTime: time } }] },
})

describe('parsing the sources', () => {
  it("reads Yahoo's latest regular-market price and its currency", () => {
    expect(parseYahoo(yahoo(6.18))).toEqual({ price: 6.18, currency: 'USD', at: new Date(1793131200 * 1000).toISOString() })
    expect(parseYahoo(yahoo(285.46, 'CAD'))?.currency).toBe('CAD')
    expect(parseYahoo(yahoo(0))).toBeNull()
    expect(parseYahoo(yahoo(10, 'GBp'))).toBeNull() // only USD and CAD listings are priced
    expect(parseYahoo({ chart: { result: null, error: { code: 'Not Found' } } })).toBeNull()
  })

  it('asks Yahoo for one symbol, escaped', () => {
    expect(yahooUrl('RCI-B.TO')).toBe('https://query1.finance.yahoo.com/v8/finance/chart/RCI-B.TO?range=1d&interval=1d')
  })

  it("takes CoinGecko's top-ranked coin for each ticker, in CAD, and skips a stale listing", () => {
    const rows = [
      { symbol: 'btc', market_cap_rank: 1, current_price: 113481, last_updated: '2026-10-28T18:10:00Z' },
      { symbol: 'btc', market_cap_rank: 4021, current_price: 0.01, last_updated: '2026-10-28T18:10:00Z' }, // a namesake
      { symbol: 'pol', market_cap_rank: 30, current_price: 0.31, last_updated: '2026-10-28T18:00:00Z' },
      { symbol: 'dead', market_cap_rank: 900, current_price: 1, last_updated: '2026-10-20T00:00:00Z' },
    ]
    expect(parseCoingecko(['BTC', 'MATIC', 'DEAD', 'NONE'], rows, NOW)).toEqual({
      BTC: { price: 113481, currency: 'CAD', at: '2026-10-28T18:10:00.000Z' },
      MATIC: { price: 0.31, currency: 'CAD', at: '2026-10-28T18:00:00.000Z' }, // MATIC trades as POL
    })
    expect(coingeckoUrl(['BTC', 'MATIC'])).toBe('https://api.coingecko.com/api/v3/coins/markets?vs_currency=cad&symbols=btc%2Cpol')
  })
})

describe('the cookie', () => {
  const quotes: LiveQuotes = { fetchedAt: NOW.toISOString(), quotes: { 'stock:VEEA': { price: 6.18, currency: 'USD', at: NOW.toISOString() } } }

  it('round-trips, and is dropped once an hour old or malformed', () => {
    expect(decodeQuotes(encodeQuotes(quotes), NOW)).toEqual(quotes)
    const later = new Date(NOW.getTime() + (QUOTES_MAX_AGE_SECONDS + 1) * 1000)
    expect(decodeQuotes(encodeQuotes(quotes), later)).toBeNull()
    expect(decodeQuotes('not json', NOW)).toBeNull()
    expect(decodeQuotes(JSON.stringify({ fetchedAt: NOW.toISOString(), quotes: { x: { price: -1 } } }), NOW)).toEqual({
      fetchedAt: NOW.toISOString(),
      quotes: {},
    })
    expect(decodeQuotes(undefined, NOW)).toBeNull()
  })
})

describe('withQuotes', () => {
  const book = new PriceBook(
    new Map([
      ['stock:VEEA', [{ day: '2026-10-27', close: 6.0, currency: 'USD' as const }]],
      ['stock:RY.TO', [{ day: '2026-10-28', close: 280, currency: 'CAD' as const }]],
      ['crypto:BTC', [{ day: '2026-10-27', close: 80000, currency: 'USD' as const }]],
    ]),
  )
  const live: LiveQuotes = {
    fetchedAt: NOW.toISOString(),
    quotes: {
      'stock:VEEA': { price: 6.18, currency: 'USD', at: NOW.toISOString() },
      'stock:RY.TO': { price: 285.46, currency: 'CAD', at: NOW.toISOString() },
      'crypto:BTC': { price: 113481, currency: 'CAD', at: NOW.toISOString() },
    },
  }

  it("makes each live quote the latest close, on the quote's Toronto day, replacing a stored close that day", () => {
    const out = withQuotes(book, live)
    expect(out.latest('stock:VEEA')).toEqual({ day: '2026-10-28', close: 6.18, currency: 'USD' })
    expect(out.latest('stock:RY.TO')).toEqual({ day: '2026-10-28', close: 285.46, currency: 'CAD' })
    expect(out.days('stock:RY.TO')).toEqual(['2026-10-28']) // replaced, not doubled
    expect(out.latest('crypto:BTC')).toEqual({ day: '2026-10-28', close: 113481, currency: 'CAD' }) // a coin's quote is in CAD
    expect(out.on('stock:VEEA', '2026-10-27')?.close).toBe(6.0) // history is untouched
  })

  it('without quotes, is the same book', () => {
    expect(withQuotes(book, null)).toBe(book)
  })
})

describe('withLiveClose', () => {
  const closes = [
    { day: '2026-10-27', close: 80000, currency: 'USD' as const },
    { day: '2026-10-28', close: 81000, currency: 'USD' as const },
  ]
  const quote = { price: 113400, currency: 'CAD' as const, at: NOW.toISOString() }

  it("ends the chart's series at the live price, in the series' own currency", () => {
    expect(withLiveClose(closes, quote, 1.4)).toEqual([closes[0], { day: '2026-10-28', close: 81000, currency: 'USD' }])
    const usd = withLiveClose(closes, { ...quote, price: 112000 }, 1.4).at(-1)
    expect(usd).toEqual({ day: '2026-10-28', close: 80000, currency: 'USD' }) // C$112,000 at 1.4
  })

  it('leaves the series alone without a quote, or without a rate to convert one', () => {
    expect(withLiveClose(closes, undefined, 1.4)).toBe(closes)
    expect(withLiveClose(closes, quote, null)).toBe(closes)
  })
})

describe('fetchQuotes', () => {
  it('prices each stock from Yahoo and the coins in one CoinGecko call, naming what it missed', async () => {
    const calls: string[] = []
    const fake = async (url: string) => {
      calls.push(url)
      if (url.includes('VEEA')) return Response.json(yahoo(6.18))
      if (url.includes('XRPN')) return new Response('Too Many Requests', { status: 429 })
      return Response.json([{ symbol: 'btc', market_cap_rank: 1, current_price: 113481, last_updated: '2026-10-28T18:10:00Z' }])
    }
    const out = await fetchQuotes(
      [
        { symbol: 'VEEA', assetType: 'stock' },
        { symbol: 'XRPN', assetType: 'stock' },
        { symbol: 'BTC', assetType: 'crypto' },
        { symbol: 'BONK', assetType: 'crypto' },
      ],
      fake,
      NOW,
    )
    expect(Object.keys(out.quotes.quotes).sort()).toEqual(['crypto:BTC', 'stock:VEEA'])
    expect(out.missing).toEqual(['XRPN', 'BONK'])
    expect(out.quotes.fetchedAt).toBe(NOW.toISOString())
    expect(calls.filter((c) => c.includes('coingecko'))).toHaveLength(1)
  })

  it('a network failure misses that source, never throws', async () => {
    const out = await fetchQuotes([{ symbol: 'VEEA', assetType: 'stock' }], async () => {
      throw new Error('offline')
    }, NOW)
    expect(out.missing).toEqual(['VEEA'])
  })
})
