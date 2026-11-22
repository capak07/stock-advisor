/** The picks' shared arithmetic, for Today and the Picks page alike. */
import type { MarketPicks } from './data/picks'

/**
 * A market's pick count, both styles: zero when its model failed its check (or has none), since the
 * Picks page then shows none of them. Today counts the same way, so the two pages never disagree.
 */
export const pickCount = (m: Pick<MarketPicks, 'enabled' | 'swing' | 'position'>): number =>
  m.enabled ? m.swing.length + m.position.length : 0
