'use server'

import { ownerClient } from '@/lib/auth'
import { loadFx, loadTrades } from '@/lib/data/portfolio'
import { todayInToronto } from '@/lib/dates'
import { fetchIntraday, portfolioDay, priceDay, type DayChart } from '@/lib/intraday'
import { buildLedger } from '@/lib/portfolio/ledger'
import { assetKey, type AssetType } from '@/lib/portfolio/types'
import { isValidSymbol } from '@/lib/symbols'

export interface PortfolioDay {
  chart: DayChart | null
  /** Held symbols Yahoo had no prices for: they're left out of the day. */
  missing: string[]
}

/** The portfolio's 1D chart: every open holding's 5-minute prices from Yahoo, valued in CAD at the latest rate. */
export async function loadPortfolioDay(): Promise<PortfolioDay> {
  const supabase = await ownerClient()
  if (!supabase) return { chart: null, missing: [] }
  const [trades, fx] = await Promise.all([loadTrades(supabase), loadFx(supabase)])
  const positions = buildLedger(trades, fx).positions
  const days = await fetchIntraday(positions)
  const usdCad = fx.on(todayInToronto())
  const missing: string[] = []
  const holdings = positions.flatMap((p) => {
    const day = days.get(assetKey(p.assetType, p.symbol))
    const toCad = day?.currency === 'USD' ? usdCad : 1
    if (!day || toCad === null) {
      missing.push(p.symbol)
      return []
    }
    return [{ qty: p.qty, toCad, day }]
  })
  return { chart: portfolioDay(holdings), missing: [...new Set(missing)] }
}

/** A stock's or coin's 1D chart: its 5-minute prices from Yahoo against the previous close; null without an answer. */
export async function loadTickerDay(symbol: string, assetType: AssetType): Promise<DayChart | null> {
  if (!(await ownerClient())) return null
  if ((assetType !== 'stock' && assetType !== 'crypto') || !isValidSymbol(symbol, assetType)) return null
  const day = (await fetchIntraday([{ symbol, assetType }])).get(assetKey(assetType, symbol))
  return day ? priceDay(day) : null
}
