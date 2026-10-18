'use server'

import { revalidatePath } from 'next/cache'
import { isListedStock } from '@/lib/data/symbols'
import type { AssetType } from '@/lib/portfolio/types'
import { createClient } from '@/lib/supabase/server'
import type { FormState } from '@/lib/trade-form'
import { parseWatch } from '@/lib/watch-form'

/** Watch a symbol. The next run prices it first and collects its data (spec §7.2). */
export async function addWatch(_: FormState, form: FormData): Promise<FormState> {
  const parsed = parseWatch(String(form.get('symbol') ?? ''), String(form.get('type') ?? ''))
  if ('error' in parsed) return { errors: { symbol: parsed.error }, at: Date.now() }
  const supabase = await createClient()
  const { error } = await supabase.from('watchlist').insert({ symbol: parsed.symbol, asset_type: parsed.assetType })
  if (error?.code === '23505') return { errors: { symbol: `${parsed.symbol} is already on the watchlist.` }, at: Date.now() }
  if (error) return { message: `It wasn't added: ${error.message}`, at: Date.now() }
  revalidatePath('/watchlist')
  revalidatePath('/ticker/[symbol]', 'page')
  const listed = parsed.assetType === 'crypto' || (await isListedStock(supabase, parsed.symbol))
  return {
    ok: true,
    message: listed
      ? `${parsed.symbol} added to the watchlist`
      : `${parsed.symbol} added. It isn't in the stock lists; the next run will try Yahoo.`,
    at: Date.now(),
  }
}

export async function removeWatch(symbol: string, assetType: AssetType): Promise<FormState> {
  const supabase = await createClient()
  const { error } = await supabase.from('watchlist').delete().eq('symbol', symbol).eq('asset_type', assetType)
  if (error) return { message: `It wasn't removed: ${error.message}`, at: Date.now() }
  revalidatePath('/watchlist')
  revalidatePath('/ticker/[symbol]', 'page')
  return { ok: true, message: `${symbol} removed from the watchlist`, at: Date.now() }
}
