import type { AssetType } from './portfolio/types'
import { isValidSymbol } from './symbols'

/** What the watchlist says when something not picked from the search's list reaches it. */
export const PICK_FROM_LIST = 'Pick a stock or coin from the list.'

/**
 * A watchlist pick: a symbol exactly as the lists store it, with its asset type. The search only
 * sends those, but a server action takes any input, so anything else is refused here before the
 * lists are asked whether they have it.
 */
export function parseWatch(symbol: unknown, assetType: unknown): { symbol: string; assetType: AssetType } | null {
  if (typeof symbol !== 'string' || (assetType !== 'stock' && assetType !== 'crypto')) return null
  return isValidSymbol(symbol, assetType) ? { symbol, assetType } : null
}
