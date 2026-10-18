'use server'

import { revalidatePath } from 'next/cache'
import { todayInToronto } from '@/lib/dates'
import { loadFx, loadTrades } from '@/lib/data/portfolio'
import { isListedStock } from '@/lib/data/symbols'
import { fmtQty } from '@/lib/format'
import { buildLedger, positionKey } from '@/lib/portfolio/ledger'
import { ACCOUNT_LABELS } from '@/lib/portfolio/types'
import { createClient } from '@/lib/supabase/server'
import { formFields, parseBuy, parseSell, type FormState } from '@/lib/trade-form'

const failed = (message: string): FormState => ({ message, at: Date.now() })

/** Add a buy (a `lots` row). Row-level security lets only the owner insert. */
export async function addBuy(_: FormState, form: FormData): Promise<FormState> {
  const fields = formFields(form)
  const parsed = parseBuy(fields, todayInToronto())
  if ('errors' in parsed) return { errors: parsed.errors, at: Date.now() }
  const buy = parsed.input
  const supabase = await createClient()

  // A held stock Yahoo can't price leaves every run degraded, so a typo is worth a second look.
  // ETFs aren't in the lists, so the owner can still confirm one.
  if (buy.assetType === 'stock' && fields.confirmUnlisted !== 'on' && !(await isListedStock(supabase, buy.symbol))) {
    return {
      confirm: `${buy.symbol} isn't in the US or TSX stock lists (ETFs aren't listed). Check the symbol, or save it anyway.`,
      at: Date.now(),
    }
  }

  let rate = buy.fxRateCad
  if (buy.currency === 'USD' && rate === null) {
    rate = (await loadFx(supabase)).on(buy.day)
    if (rate === null) {
      return { errors: { fxRate: 'No Bank of Canada rate on or before that day yet; enter the rate.' }, at: Date.now() }
    }
  }

  const { error } = await supabase.from('lots').insert({
    account: buy.account,
    symbol: buy.symbol,
    asset_type: buy.assetType,
    qty: buy.qty,
    price: buy.price,
    currency: buy.currency,
    fx_rate_cad: buy.currency === 'USD' ? rate : null,
    bought_at: buy.day,
    notes: buy.notes,
  })
  if (error) return failed(`The buy wasn't saved: ${error.message}`)
  revalidatePath('/')
  return { ok: true, message: `Buy saved: ${fmtQty(buy.qty)} ${buy.symbol} in ${ACCOUNT_LABELS[buy.account]}`, at: Date.now() }
}

/**
 * Delete a buy or a sell (Plan 5c). Row-level security lets only the owner delete; a row that
 * isn't there (deleted in another tab) is reported, not ignored.
 */
export async function deleteTrade(side: 'buy' | 'sell', id: number): Promise<FormState> {
  if ((side !== 'buy' && side !== 'sell') || !Number.isSafeInteger(id) || id <= 0) {
    return failed("That trade can't be deleted.")
  }
  const supabase = await createClient()
  const { data, error } = await supabase
    .from(side === 'buy' ? 'lots' : 'sells')
    .delete()
    .eq('id', id)
    .select('symbol, qty')
  if (error) return failed(`The ${side} wasn't deleted: ${error.message}`)
  const row = (data as { symbol: string; qty: string | number }[] | null)?.[0]
  if (!row) return failed(`That ${side} was already gone.`)
  revalidatePath('/')
  return {
    ok: true,
    message: `${side === 'buy' ? 'Buy' : 'Sell'} deleted: ${fmtQty(Number(row.qty))} ${row.symbol}`,
    at: Date.now(),
  }
}

/** Add a sell (a `sells` row), checked against what the ledger says is held. */
export async function addSell(_: FormState, form: FormData): Promise<FormState> {
  const supabase = await createClient()
  const [trades, fx] = await Promise.all([loadTrades(supabase), loadFx(supabase)])
  const held = buildLedger(trades, fx).positions.map((p) => ({ ...p, key: positionKey(p) }))
  const parsed = parseSell(formFields(form), held, todayInToronto())
  if ('errors' in parsed) return { errors: parsed.errors, at: Date.now() }
  const sell = parsed.input

  let rate = sell.fxRateCad
  if (sell.currency === 'USD' && rate === null) {
    rate = fx.on(sell.day)
    if (rate === null) {
      return { errors: { fxRate: 'No Bank of Canada rate on or before that day yet; enter the rate.' }, at: Date.now() }
    }
  }

  const { error } = await supabase.from('sells').insert({
    account: sell.account,
    symbol: sell.symbol,
    asset_type: sell.assetType,
    qty: sell.qty,
    price: sell.price,
    currency: sell.currency,
    fx_rate_cad: sell.currency === 'USD' ? rate : null,
    sold_at: sell.day,
  })
  if (error) return failed(`The sell wasn't saved: ${error.message}`)
  revalidatePath('/')
  return { ok: true, message: `Sell saved: ${fmtQty(sell.qty)} ${sell.symbol} from ${ACCOUNT_LABELS[sell.account]}`, at: Date.now() }
}
