import type { AssetType } from './portfolio/types'
import { normalizeSymbol } from './symbols'

/** One thing the search can offer: a listed US or TSX stock, or one of the stored top coins. */
export interface SearchItem {
  symbol: string
  name: string
  assetType: AssetType
  kind: 'US' | 'TSX' | 'Crypto'
}

export const MAX_RESULTS = 8
const KIND_ORDER = { TSX: 0, US: 1, Crypto: 2 } as const

/** What a match counts for: the ticker itself, a ticker that starts with the query, a name word
 * that does, then anywhere in the name. Lower is better; null is no match. */
function score(item: SearchItem, words: string, ticker: string): number | null {
  if (item.symbol === ticker || item.symbol.replace(/\.TO$/, '') === ticker) return 0
  if (item.symbol.startsWith(ticker)) return 1
  const name = item.name.toLowerCase()
  if (name.split(/[\s,.()&-]+/).some((word) => word.startsWith(words))) return 2
  return name.includes(words) ? 3 : null
}

/**
 * The best matches for what's been typed: by score, then TSX before US before coins, then the
 * list's own order (coins come best-ranked first).
 */
export function searchSymbols(items: readonly SearchItem[], query: string, max = MAX_RESULTS): SearchItem[] {
  const words = query.trim().toLowerCase()
  if (!words) return []
  const ticker = normalizeSymbol(query)
  const scored: { item: SearchItem; score: number; index: number }[] = []
  items.forEach((item, index) => {
    const s = score(item, words, ticker)
    if (s !== null) scored.push({ item, score: s, index })
  })
  scored.sort((a, b) => a.score - b.score || KIND_ORDER[a.item.kind] - KIND_ORDER[b.item.kind] || a.index - b.index)
  return scored.slice(0, max).map((s) => s.item)
}

// What follows a company in a directory name: " - Common Stock", " Class A Subordinate Voting
// Shares", " New Common Stock", " American Depositary Shares (each representing …)".
const SHARE_DESCRIPTION =
  /\s+(?:-\s.*|(?:New\s+)?(?:Class\s+[A-Z]\s+)?(?:Common|Ordinary|Capital|Subordinate Voting|Limited Voting|Voting)\s+(?:Stock|Shares).*|American Depositary.*|Sponsored ADR.*)$/i

/** A directory name without its share description, for display. */
export const displayName = (name: string): string => name.replace(SHARE_DESCRIPTION, '').trim() || name

/** The name split around the matched part, preferring a match at the start of a word. */
export function highlight(name: string, query: string): { text: string; match: boolean }[] {
  const needle = query.trim().toLowerCase()
  const lower = name.toLowerCase()
  let at = needle ? lower.search(new RegExp(`(^|[^a-z0-9])${needle.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`)) : -1
  if (at >= 0 && !lower.startsWith(needle, at)) at += 1 // skip the separator the pattern matched
  if (at < 0 && needle) at = lower.indexOf(needle)
  if (at < 0) return [{ text: name, match: false }]
  const parts = [
    { text: name.slice(0, at), match: false },
    { text: name.slice(at, at + needle.length), match: true },
    { text: name.slice(at + needle.length), match: false },
  ]
  return parts.filter((part) => part.text)
}
