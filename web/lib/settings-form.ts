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
  /** C$; the Runners page sizes shares so the loss at the stop fits it. */
  runners_max_loss_cad: number
  /** The owner's combined federal and provincial marginal rate, in percent; null until set (no after-tax figures). */
  marginal_tax_pct: number | null
}

/** The owner-editable settings (spec §3, §7.5, the day trade tab's two, the Runners max loss and the tax rate), within the database's CHECK limits. */
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
  const maxLoss = (name: string) => {
    const value = parseAmount(form[name])
    if (value === null || value <= 0 || value > 100_000) errors[name] = 'Enter a max loss above C$0, up to C$100,000.'
    return value ?? 0
  }
  const daytradeMaxLoss = maxLoss('daytrade_max_loss_cad')
  const spread = parseAmount(form.daytrade_spread_pct)
  if (spread === null || spread > 5) errors.daytrade_spread_pct = 'Enter a spread from 0 to 5%.'
  const runnersMaxLoss = maxLoss('runners_max_loss_cad')
  const blank = (form.marginal_tax_pct ?? '').trim() === ''
  const tax = blank ? null : parseAmount(form.marginal_tax_pct)
  if (!blank && (tax === null || tax > 100)) errors.marginal_tax_pct = 'Enter a rate from 0 to 100%, or leave it blank.'
  if (Object.keys(errors).length > 0) return { errors }
  return {
    input: {
      usd_fx_fee_pct: usd,
      crypto_fee_pct: crypto,
      tfsa_round_trips_warn: trips as number,
      tfsa_short_hold_share_warn: (share as number) / 100,
      daytrade_max_loss_cad: daytradeMaxLoss,
      daytrade_spread_pct: spread as number,
      runners_max_loss_cad: runnersMaxLoss,
      marginal_tax_pct: tax,
    },
  }
}
