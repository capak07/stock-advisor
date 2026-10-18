'use server'

import { revalidatePath } from 'next/cache'
import { todayInToronto } from '@/lib/dates'
import { must } from '@/lib/data/fetch'
import { loadFx, loadTrades } from '@/lib/data/portfolio'
import { sameTrade, type ImportTrade } from '@/lib/import/rows'
import { buildLedger } from '@/lib/portfolio/ledger'
import { ACCOUNTS } from '@/lib/portfolio/types'
import type { Trade } from '@/lib/portfolio/types'
import { createClient } from '@/lib/supabase/server'
import { isValidSymbol, tradeCurrency } from '@/lib/symbols'
import { RATE_RANGE, type FormState } from '@/lib/trade-form'

/** The most trades one file may add: years of a personal account's activity. */
const MAX_TRADES = 5000

const failed = (message: string): FormState => ({ message, at: Date.now() })

/** Stock symbols missing from the US and TSX lists (ETFs aren't listed), for the review step. */
export async function unlistedStocks(symbols: string[]): Promise<string[]> {
  const wanted = [...new Set(symbols)].filter((s) => isValidSymbol(s, 'stock')).slice(0, MAX_TRADES)
  if (wanted.length === 0) return []
  const supabase = await createClient()
  const found = new Set<string>()
  for (let i = 0; i < wanted.length; i += 200) {
    const rows = must(
      await supabase.from('symbols').select('symbol').eq('asset_type', 'stock').in('symbol', wanted.slice(i, i + 200)),
    ) as { symbol: string }[]
    for (const r of rows) found.add(r.symbol)
  }
  return wanted.filter((s) => !found.has(s)).sort()
}

const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/

/** The trade the browser sent, checked again: the server trusts nothing it didn't check. */
function checked(t: ImportTrade, today: string): string | null {
  if (t.side !== 'buy' && t.side !== 'sell') return 'a trade that is neither a buy nor a sell'
  if (!ACCOUNTS.includes(t.account)) return 'an unknown account'
  if (t.assetType !== (t.account === 'crypto' ? 'crypto' : 'stock')) return 'an asset in the wrong account'
  if (!isValidSymbol(t.symbol, t.assetType)) return `the symbol "${t.symbol}"`
  if (!(Number.isFinite(t.qty) && t.qty > 0 && Number.isFinite(t.price) && t.price > 0)) return 'a quantity or price below 0'
  if (!ISO_DAY.test(t.day) || t.day > today) return `the date "${t.day}"`
  if (t.fxRate !== null && !(t.fxRate >= RATE_RANGE[0] && t.fxRate <= RATE_RANGE[1])) return `the rate ${t.fxRate}`
  return null
}

/**
 * Add a file's trades (Plan 5c). All or nothing: every trade is checked again, trades already
 * recorded are skipped, sells must not exceed what's held once the file's buys are in, and USD
 * trades without a rate get the Bank of Canada's for their day.
 */
export async function importTrades(trades: ImportTrade[]): Promise<FormState> {
  if (!Array.isArray(trades) || trades.length === 0) return failed('There are no trades to import.')
  if (trades.length > MAX_TRADES) return failed(`One file can add at most ${MAX_TRADES} trades.`)
  const today = todayInToronto()
  for (const t of trades) {
    const problem = checked(t, today)
    if (problem) return failed(`Nothing was imported: one trade has ${problem}.`)
  }

  const supabase = await createClient()
  const [existing, fx] = await Promise.all([loadTrades(supabase), loadFx(supabase)])
  // The review only knew the trades recorded when the page loaded; another tab may have added some.
  const fresh = trades.filter((t) => !existing.some((e) => sameTrade(e, t)))
  if (fresh.length === 0) return failed(`All ${trades.length} of these trades are already recorded.`)
  const incoming: Trade[] = []
  for (const t of fresh) {
    const currency = tradeCurrency(t.assetType, t.symbol)
    const rate = currency === 'USD' ? (t.fxRate ?? fx.on(t.day)) : null
    if (currency === 'USD' && rate === null) {
      return failed(
        `Nothing was imported: there's no Bank of Canada rate stored for ${t.symbol} on ${t.day}. Add a USD/CAD rate column to the file, or add that trade under Buy or Sell with its rate.`,
      )
    }
    incoming.push({ ...t, currency, fxRateCad: rate })
  }

  const before = new Set(buildLedger(existing, fx).problems)
  const added = buildLedger([...existing, ...incoming], fx).problems.filter((p) => !before.has(p))
  if (added.length > 0) {
    return failed(`Nothing was imported. ${added.slice(0, 3).join(' ')}${added.length > 3 ? ` (and ${added.length - 3} more)` : ''}`)
  }

  const row = (t: Trade) => ({
    account: t.account,
    symbol: t.symbol,
    asset_type: t.assetType,
    qty: t.qty,
    price: t.price,
    currency: t.currency,
    fx_rate_cad: t.fxRateCad,
  })
  const buys = incoming.filter((t) => t.side === 'buy').map((t) => ({ ...row(t), bought_at: t.day, notes: 'Imported' }))
  const sells = incoming.filter((t) => t.side === 'sell').map((t) => ({ ...row(t), sold_at: t.day }))

  let buyIds: number[] = []
  if (buys.length > 0) {
    const { data, error } = await supabase.from('lots').insert(buys).select('id')
    if (error) return failed(`Nothing was imported: ${error.message}`)
    buyIds = (data as { id: number }[]).map((r) => r.id)
  }
  if (sells.length > 0) {
    const { error } = await supabase.from('sells').insert(sells)
    if (error) {
      // Undo the buys, so a failed file leaves nothing behind.
      if (buyIds.length > 0) {
        const { error: undoError } = await supabase.from('lots').delete().in('id', buyIds)
        if (undoError) {
          revalidatePath('/')
          return failed(
            `Only the buys went in: the sells failed (${error.message}) and the ${buyIds.length} buys couldn't be taken back. Delete them under Trades, then import the file again.`,
          )
        }
      }
      return failed(`Nothing was imported: ${error.message}`)
    }
  }
  revalidatePath('/')
  const n = incoming.length
  const skipped = trades.length - n
  const note = skipped > 0 ? ` (${skipped} already recorded, skipped)` : ''
  return { ok: true, message: `Imported ${n} ${n === 1 ? 'trade' : 'trades'}${note}`, at: Date.now() }
}
