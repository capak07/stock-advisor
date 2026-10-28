'use server'

import { cookies } from 'next/headers'
import { revalidatePath } from 'next/cache'
import { ownerClient } from '@/lib/auth'
import { loadFx, loadTrades } from '@/lib/data/portfolio'
import { loadWatchlist } from '@/lib/data/watchlist'
import { buildLedger } from '@/lib/portfolio/ledger'
import { QUOTES_COOKIE, QUOTES_MAX_AGE_SECONDS, encodeQuotes, fetchQuotes } from '@/lib/quotes'

export interface RefreshResult {
  ok: boolean
  message: string
  at: number
}

/**
 * Refresh: live prices for every held and watched asset, kept in a private cookie for an hour
 * (lib/quotes.ts). Forecasts and actions stay from the last run.
 */
export async function refreshQuotes(): Promise<RefreshResult> {
  const supabase = await ownerClient()
  if (!supabase) return { ok: false, message: 'Only the owner can refresh prices.', at: Date.now() }
  const [trades, watch, fx] = await Promise.all([loadTrades(supabase), loadWatchlist(supabase), loadFx(supabase)])
  const assets = [
    ...buildLedger(trades, fx).positions.map((p) => ({ symbol: p.symbol, assetType: p.assetType })),
    ...watch.map((w) => ({ symbol: w.symbol, assetType: w.assetType })),
  ]
  if (assets.length === 0) return { ok: false, message: 'Nothing held or watched to price.', at: Date.now() }

  const { quotes, missing } = await fetchQuotes(assets)
  const priced = Object.keys(quotes.quotes).length
  if (priced > 0) {
    ;(await cookies()).set(QUOTES_COOKIE, encodeQuotes(quotes), {
      httpOnly: true,
      sameSite: 'lax',
      secure: process.env.NODE_ENV === 'production',
      maxAge: QUOTES_MAX_AGE_SECONDS,
      path: '/',
    })
    revalidatePath('/', 'layout')
  }
  const total = priced + missing.length
  if (priced === 0) return { ok: false, message: `No live prices: Yahoo and CoinGecko didn't answer. Showing the last run's.`, at: Date.now() }
  const note = missing.length ? ` No answer for ${missing.join(', ')}: those keep the last run's price.` : ''
  return { ok: true, message: `Live prices for ${priced} of ${total}.${note}`, at: Date.now() }
}
