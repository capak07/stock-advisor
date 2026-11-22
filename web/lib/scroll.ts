/** Moves shorter than this are jitter (a finger resting on the glass, momentum settling) and change nothing. */
export const SCROLL_JITTER_PX = 6
/** Near the top of the page the tab bar always shows. */
export const SCROLL_TOP_PX = 120

/**
 * Whether the phone tab bar should be hidden after the page scrolled from `prevY` to `y` (spec §5): it hides
 * while scrolling down past the top 120 px and comes back on any scroll up. A move under 6 px keeps it as it is.
 */
export function nextHidden(prevY: number, y: number, hidden: boolean): boolean {
  if (Math.abs(y - prevY) < SCROLL_JITTER_PX) return hidden
  return y > prevY && y > SCROLL_TOP_PX
}
