/**
 * The cookie a browser test pins the server's clock with. The server honours it only when it was
 * started with E2E_CLOCK=1, which playwright.config.ts sets and nothing else does: a page whose
 * output depends on the time of day (the Day trade page stops being live at 4:05 PM ET) can then be
 * tested at any hour.
 */
export const E2E_NOW_COOKIE = 'e2e-now'

/** The time a page renders at, as an ISO string: the pinned one when pinning is on and `pinned` is a
 * time, otherwise `real`. */
export function clockNow(real: Date, pinned: string | undefined, enabled: boolean): string {
  if (enabled && pinned) {
    const t = Date.parse(pinned)
    if (Number.isFinite(t)) return new Date(t).toISOString()
  }
  return real.toISOString()
}
