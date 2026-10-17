import type { AssetType, Currency, Market } from './portfolio/types'

/** The symbol formats the database's CHECK constraints enforce (spec §8). */
export const US_STOCK = /^[A-Z]{1,5}(\.[A-Z])?$/
export const TSX_STOCK = /^[A-Z]{1,5}(-[A-Z]{1,2})?\.TO$/
export const COIN = /^[A-Z0-9]{2,10}$/

/**
 * Upper-case and trim. A TSX class written with a dot (RCI.B.TO) becomes Yahoo's form (RCI-B.TO),
 * which is how the pipeline stores TSX symbols.
 */
export const normalizeSymbol = (raw: string): string => {
  const symbol = raw.trim().toUpperCase()
  const dotted = /^([A-Z]{1,5})\.([A-Z]{1,2})\.TO$/.exec(symbol)
  return dotted ? `${dotted[1]}-${dotted[2]}.TO` : symbol
}

export const isValidSymbol = (symbol: string, assetType: AssetType): boolean =>
  assetType === 'crypto' ? COIN.test(symbol) : US_STOCK.test(symbol) || TSX_STOCK.test(symbol)

export const marketOf = (symbol: string): Market => (symbol.endsWith('.TO') ? 'TSX' : 'US')

/** Wealthsimple trades US stocks in USD and everything else, coins included, in CAD (spec rev 2). */
export const tradeCurrency = (assetType: AssetType, symbol: string): Currency =>
  assetType === 'stock' && marketOf(symbol) === 'US' ? 'USD' : 'CAD'
