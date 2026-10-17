import type { AssetType } from './portfolio/types'
import { isValidSymbol, normalizeSymbol } from './symbols'

export type WatchType = 'us' | 'tsx' | 'crypto'
export const WATCH_TYPES: { value: WatchType; label: string }[] = [
  { value: 'us', label: 'US stock' },
  { value: 'tsx', label: 'TSX stock' },
  { value: 'crypto', label: 'Crypto' },
]

/**
 * A symbol for the watchlist (spec §9: US stocks, TSX stocks and crypto). A TSX stock typed
 * without its suffix gets ".TO"; a US stock can't have one.
 */
export function parseWatch(rawSymbol: string, type: string): { symbol: string; assetType: AssetType } | { error: string } {
  let symbol = normalizeSymbol(rawSymbol)
  if (!symbol) return { error: 'Enter a symbol.' }
  if (type === 'crypto') {
    return isValidSymbol(symbol, 'crypto') ? { symbol, assetType: 'crypto' } : { error: 'Enter a coin symbol, like ETH.' }
  }
  if (type === 'tsx') {
    if (!symbol.endsWith('.TO')) symbol = normalizeSymbol(`${symbol.replace('.', '-')}.TO`)
    return isValidSymbol(symbol, 'stock') ? { symbol, assetType: 'stock' } : { error: 'Enter a TSX symbol, like SHOP or RCI-B.' }
  }
  if (type === 'us') {
    if (symbol.endsWith('.TO')) return { error: 'Symbols ending in .TO are TSX stocks; pick TSX stock.' }
    return isValidSymbol(symbol, 'stock') ? { symbol, assetType: 'stock' } : { error: 'Enter a US symbol, like NVDA or BRK.B.' }
  }
  return { error: 'Pick a type.' }
}
