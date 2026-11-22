/**
 * The phone Search sheet's recent stocks (spec §6): kept per device in local storage, newest first, updated when a
 * stock page opens. Storage that is missing, blocked or hand-edited reads as an empty list, and nothing here throws.
 */

import { isValidSymbol } from './symbols'

export const RECENT_KEY = 'advisor.recent-symbols'
const MAX = 8

const isSymbol = (value: unknown): value is string =>
  typeof value === 'string' && (isValidSymbol(value, 'stock') || isValidSymbol(value, 'crypto'))

/** `symbol` first, then the rest without it, at most `max`. */
export function pushRecent(list: readonly string[], symbol: string, max = MAX): string[] {
  return [symbol, ...list.filter((s) => s !== symbol)].slice(0, max)
}

/** The stored list, keeping only real symbols (a stored value is never trusted), at most 8. */
export function readRecent(storage: Pick<Storage, 'getItem'> | null): string[] {
  try {
    const raw = storage?.getItem(RECENT_KEY)
    if (!raw) return []
    const parsed: unknown = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed.filter(isSymbol).slice(0, MAX) : []
  } catch {
    return [] // blocked storage (a private window, a WebView) or a value that isn't JSON
  }
}

/** This device's local storage, or null on the server or where even reading `localStorage` throws (a blocked WebView). */
export function deviceStorage(): Storage | null {
  try {
    return typeof window === 'undefined' ? null : window.localStorage
  } catch {
    return null
  }
}

/** Store the list; a full or blocked storage just keeps the old one. */
export function writeRecent(storage: Pick<Storage, 'setItem'> | null, list: readonly string[]): void {
  try {
    storage?.setItem(RECENT_KEY, JSON.stringify(list))
  } catch {
    // quota exceeded or storage blocked: recent searches are a convenience
  }
}
