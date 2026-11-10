import 'server-only'
import type { Supabase } from '../supabase/server'
import { must } from './fetch'

/** The one `settings` row (spec §8). */
export interface Settings {
  usd_fx_fee_pct: number
  crypto_fee_pct: number
  tfsa_round_trips_warn: number
  tfsa_short_hold_share_warn: number
  daytrade_max_loss_cad: number
  daytrade_spread_pct: number
  updated_at: string
}

export async function loadSettings(supabase: Supabase): Promise<Settings> {
  const row = must(
    await supabase
      .from('settings')
      .select(
        'usd_fx_fee_pct, crypto_fee_pct, tfsa_round_trips_warn, tfsa_short_hold_share_warn, daytrade_max_loss_cad, daytrade_spread_pct, updated_at',
      )
      .eq('id', 1)
      .single(),
  ) as Record<string, string | number>
  return {
    usd_fx_fee_pct: Number(row.usd_fx_fee_pct),
    crypto_fee_pct: Number(row.crypto_fee_pct),
    tfsa_round_trips_warn: Number(row.tfsa_round_trips_warn),
    tfsa_short_hold_share_warn: Number(row.tfsa_short_hold_share_warn),
    daytrade_max_loss_cad: Number(row.daytrade_max_loss_cad),
    daytrade_spread_pct: Number(row.daytrade_spread_pct),
    updated_at: String(row.updated_at),
  }
}
