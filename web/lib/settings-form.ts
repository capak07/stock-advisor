import { parseAmount, type FieldErrors } from './trade-form'

export interface SettingsInput {
  usd_fx_fee_pct: number
  crypto_fee_pct: number
  tfsa_round_trips_warn: number
  /** 0..1; the form shows it as a percentage. */
  tfsa_short_hold_share_warn: number
  /** C$; the day trade tab sizes shares so the loss at the stop fits it. */
  daytrade_max_loss_cad: number
  /** The day trade tab's round-trip spread, in percent. */
  daytrade_spread_pct: number
}

/** The owner-editable settings (spec §3, §7.5, and the day trade tab's two), within the database's CHECK limits. */
export function parseSettings(form: Record<string, string>): { input: SettingsInput } | { errors: FieldErrors } {
  const errors: FieldErrors = {}
  const fee = (name: string, label: string) => {
    const value = parseAmount(form[name])
    if (value === null || value > 10) errors[name] = `Enter a ${label} from 0 to 10%.`
    return value ?? 0
  }
  const usd = fee('usd_fx_fee_pct', 'fee')
  const crypto = fee('crypto_fee_pct', 'spread')
  const trips = parseAmount(form.tfsa_round_trips_warn)
  if (trips === null || !Number.isInteger(trips) || trips < 1 || trips > 1000) {
    errors.tfsa_round_trips_warn = 'Enter a whole number from 1 to 1,000.'
  }
  const share = parseAmount(form.tfsa_short_hold_share_warn)
  if (share === null || share < 1 || share > 100) errors.tfsa_short_hold_share_warn = 'Enter a share from 1 to 100%.'
  const maxLoss = parseAmount(form.daytrade_max_loss_cad)
  if (maxLoss === null || maxLoss <= 0 || maxLoss > 100_000) {
    errors.daytrade_max_loss_cad = 'Enter a max loss above C$0, up to C$100,000.'
  }
  const spread = parseAmount(form.daytrade_spread_pct)
  if (spread === null || spread > 5) errors.daytrade_spread_pct = 'Enter a spread from 0 to 5%.'
  if (Object.keys(errors).length > 0) return { errors }
  return {
    input: {
      usd_fx_fee_pct: usd,
      crypto_fee_pct: crypto,
      tfsa_round_trips_warn: trips as number,
      tfsa_short_hold_share_warn: (share as number) / 100,
      daytrade_max_loss_cad: maxLoss as number,
      daytrade_spread_pct: spread as number,
    },
  }
}
