'use server'

import { revalidatePath } from 'next/cache'
import { isWatchable } from '@/lib/data/symbols'
import type { AssetType } from '@/lib/portfolio/types'
import { createClient } from '@/lib/supabase/server'
import type { FormState } from '@/lib/trade-form'
import { PICK_FROM_LIST, parseWatch } from '@/lib/watch-form'

/**
 * Watch a stock or coin picked from the search's list (spec §9); nothing else is taken, so a typed
 * name can't become a symbol. The next run prices it first and collects its data (spec §7.2).
 */
export async function addWatch(rawSymbol: string, rawAssetType: AssetType): Promise<FormState> {
  const pick = parseWatch(rawSymbol, rawAssetType)
  const supabase = await createClient()
  if (!pick || !(await isWatchable(supabase, pick.symbol, pick.assetType))) {
    return { errors: { symbol: PICK_FROM_LIST }, at: Date.now() }
  }
  const { error } = await supabase.from('watchlist').insert({ symbol: pick.symbol, asset_type: pick.assetType })
  if (error?.code === '23505') return { errors: { symbol: `${pick.symbol} is already on the watchlist.` }, at: Date.now() }
  if (error) return { message: `It wasn't added: ${error.message}`, at: Date.now() }
  revalidatePath('/watchlist')
  revalidatePath('/ticker/[symbol]', 'page')
  return { ok: true, message: `${pick.symbol} added to the watchlist`, at: Date.now() }
}

export async function removeWatch(symbol: string, assetType: AssetType): Promise<FormState> {
  const supabase = await createClient()
  const { error } = await supabase.from('watchlist').delete().eq('symbol', symbol).eq('asset_type', assetType)
  if (error) return { message: `It wasn't removed: ${error.message}`, at: Date.now() }
  revalidatePath('/watchlist')
  revalidatePath('/ticker/[symbol]', 'page')
  return { ok: true, message: `${symbol} removed from the watchlist`, at: Date.now() }
}
