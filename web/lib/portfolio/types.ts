/** The portfolio's inputs, as the dashboard reads them from Supabase (spec §7, §8). */

export type Account = 'tfsa' | 'rrsp' | 'fhsa' | 'non_registered' | 'crypto'
export type AssetType = 'stock' | 'crypto'
export type Currency = 'CAD' | 'USD'
export type Market = 'US' | 'TSX'

export const ACCOUNTS: readonly Account[] = ['tfsa', 'rrsp', 'fhsa', 'non_registered', 'crypto']
export const ACCOUNT_LABELS: Record<Account, string> = {
  tfsa: 'TFSA',
  rrsp: 'RRSP',
  fhsa: 'FHSA',
  non_registered: 'Non-registered',
  crypto: 'Crypto',
}
/** Accounts whose gains are taxed (spec §7.5); the others are sheltered. */
export const TAXABLE: ReadonlySet<Account> = new Set(['crypto', 'non_registered'])

/** A buy (a `lots` row) or a sell (a `sells` row). Days are ISO dates, `YYYY-MM-DD`. */
export interface Trade {
  side: 'buy' | 'sell'
  account: Account
  symbol: string
  assetType: AssetType
  qty: number
  price: number
  currency: Currency
  /** CAD per USD for a USD trade; null for CAD trades and for USD trades from before spec rev 2. */
  fxRateCad: number | null
  day: string
}

/** One stored daily close (`daily_closes`). */
export interface Close {
  day: string
  close: number
  currency: Currency
}

/** The key an asset's closes are stored under. */
export const assetKey = (assetType: AssetType, symbol: string): string => `${assetType}:${symbol}`

/** A held asset in one account, at average cost (adjusted cost base) in CAD. */
export interface Position {
  account: Account
  symbol: string
  assetType: AssetType
  qty: number
  costCad: number
  /** The day the position last went from nothing held to something held. */
  openedOn: string
}

/** A sell's result at average cost, in CAD. */
export interface Sale {
  account: Account
  symbol: string
  assetType: AssetType
  day: string
  qty: number
  proceedsCad: number
  costCad: number
  gainCad: number
  /** Days since the position was opened. */
  heldDays: number
}
