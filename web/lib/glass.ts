/** Liquid refraction (the SVG displacement filter behind the bars) is drawn only by Chrome-based browsers. */

/** Firefox, and the iOS browsers that are WebKit underneath while saying "Chrome" in their user agent. */
const NOT_CHROMIUM = ['Firefox/', 'CriOS/', 'FxiOS/', 'EdgiOS/']

/**
 * True in Chrome, Edge and the Android WebView: the brands (navigator.userAgentData) name Chromium,
 * or, where there are no brands, the user agent says Chrome and is not one of the look-alikes above.
 * Detected in script because a browser can parse `backdrop-filter: url(#liquid)` and still not draw it.
 */
export function supportsLiquidGlass(brands: readonly { brand: string }[] | undefined, userAgent: string): boolean {
  if (brands?.some((b) => b.brand === 'Chromium')) return true
  return userAgent.includes('Chrome/') && !NOT_CHROMIUM.some((token) => userAgent.includes(token))
}
