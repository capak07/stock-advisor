'use server'

import { revalidatePath } from 'next/cache'
import { MAX_ACTIVE_ALERTS, parseAlert } from '@/lib/alert-form'
import { countActiveAlerts, isKnownAsset } from '@/lib/data/alerts'
import { createClient } from '@/lib/supabase/server'
import type { FormState } from '@/lib/trade-form'

const refresh = () => {
  revalidatePath('/')
  revalidatePath('/ticker/[symbol]', 'page')
}

const text = (data: FormData, name: string): string => {
  const v = data.get(name)
  return typeof v === 'string' ? v : ''
}

/** Add an above/below alert on a stock or coin; the run checks it against the latest price. */
export async function addAlert(_prev: FormState, data: FormData): Promise<FormState> {
  const parsed = parseAlert({
    symbol: text(data, 'symbol'),
    assetType: text(data, 'assetType'),
    direction: text(data, 'direction'),
    level: text(data, 'level'),
    note: text(data, 'note'),
  })
  if (!parsed.ok) return { errors: parsed.errors, at: Date.now() }
  const { symbol, assetType, direction, level, note } = parsed.value
  const supabase = await createClient()
  if (!(await isKnownAsset(supabase, symbol, assetType))) {
    return { errors: { symbol: `${symbol} is not a stock or coin this app knows.` }, at: Date.now() }
  }
  let active: number
  try {
    active = await countActiveAlerts(supabase, symbol, assetType)
  } catch (e) {
    return { message: `It wasn't saved: ${e instanceof Error ? e.message : 'unknown error'}`, at: Date.now() }
  }
  if (active >= MAX_ACTIVE_ALERTS) {
    return { message: `${symbol} already has ${MAX_ACTIVE_ALERTS} active alerts. Delete one first.`, at: Date.now() }
  }
  const { error } = await supabase.from('price_alerts').insert({ symbol, asset_type: assetType, direction, level, note })
  if (error) return { message: `It wasn't saved: ${error.message}`, at: Date.now() }
  refresh()
  return { ok: true, message: `Alert set: ${symbol} ${direction} ${level}`, at: Date.now() }
}

const validId = (id: unknown): id is number => typeof id === 'number' && Number.isSafeInteger(id) && id > 0

/** Hide a hit alert from My Portfolio and the ticker page. */
export async function dismissAlert(id: number): Promise<FormState> {
  if (!validId(id)) return { message: 'That alert was not found.', at: Date.now() }
  const supabase = await createClient()
  const { data, error } = await supabase
    .from('price_alerts')
    .update({ dismissed_at: new Date().toISOString() })
    .eq('id', id)
    .not('hit_at', 'is', null)
    .select('id')
  if (error) return { message: `It wasn't dismissed: ${error.message}`, at: Date.now() }
  if (!data?.length) return { message: 'That alert was not found.', at: Date.now() }
  refresh()
  return { ok: true, message: 'Alert dismissed', at: Date.now() }
}

export async function deleteAlert(id: number): Promise<FormState> {
  if (!validId(id)) return { message: 'That alert was not found.', at: Date.now() }
  const supabase = await createClient()
  const { data, error } = await supabase.from('price_alerts').delete().eq('id', id).select('id')
  if (error) return { message: `It wasn't deleted: ${error.message}`, at: Date.now() }
  if (!data?.length) return { message: 'That alert was not found.', at: Date.now() }
  refresh()
  return { ok: true, message: 'Alert deleted', at: Date.now() }
}
