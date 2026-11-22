import { describe, expect, it } from 'vitest'
import { LIQUID_SCRIPT, supportsLiquidGlass } from './glass'
import { THEME_SCRIPT } from './theme'

const CHROME = [[{ brand: 'Chromium' }, { brand: 'Google Chrome' }], '']
const EDGE = [[{ brand: 'Microsoft Edge' }, { brand: 'Chromium' }], '']
const WEBVIEW = [undefined, 'Mozilla/5.0 (Linux; Android 14; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/131.0 Mobile Safari/537.36']
const FIREFOX = [undefined, 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0']
const SAFARI = [undefined, 'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15']
const CHROME_IOS = [undefined, 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/131.0 Mobile/15E148 Safari/604.1']
type Browser = [readonly { brand: string }[] | undefined, string]
const BROWSERS = { CHROME, EDGE, WEBVIEW, FIREFOX, SAFARI, CHROME_IOS } as unknown as Record<string, Browser>

describe('supportsLiquidGlass', () => {
  it('is true for Chrome, Edge and the Android WebView', () => {
    for (const [brands, ua] of [CHROME, EDGE, WEBVIEW] as unknown as Browser[]) expect(supportsLiquidGlass(brands, ua)).toBe(true)
  })
  it('is false for Firefox, Safari and Chrome on iOS (WebKit underneath)', () => {
    for (const [brands, ua] of [FIREFOX, SAFARI, CHROME_IOS] as unknown as Browser[]) expect(supportsLiquidGlass(brands, ua)).toBe(false)
  })
})

/** Runs the inline <head> script against a stand-in navigator and <html>, and says whether it set "liquid". */
function runScript(brands: Browser[0], userAgent: string, html = new Set<string>()): boolean {
  const navigator = { userAgent, ...(brands ? { userAgentData: { brands } } : {}) }
  const document = { documentElement: { classList: { add: (c: string) => html.add(c) } } }
  new Function('navigator', 'document', LIQUID_SCRIPT)(navigator, document)
  return html.has('liquid')
}

describe('LIQUID_SCRIPT', () => {
  it('marks <html> liquid before first paint exactly when supportsLiquidGlass would', () => {
    for (const [name, [brands, ua]] of Object.entries(BROWSERS)) {
      expect(runScript(brands, ua), name).toBe(supportsLiquidGlass(brands, ua))
    }
  })
  it('never throws, even without a navigator', () => {
    expect(() => new Function('navigator', 'document', LIQUID_SCRIPT)(undefined, undefined)).not.toThrow()
  })
})

describe('THEME_SCRIPT', () => {
  it('sets dark from the saved choice and then liquid, as one valid script', () => {
    const html = new Map<string, boolean>()
    const document = { documentElement: { classList: { toggle: (c: string, on: boolean) => html.set(c, on), add: (c: string) => html.set(c, true) } } }
    const localStorage = { getItem: () => 'dark' }
    const matchMedia = () => ({ matches: false })
    const [brands, ua] = BROWSERS.CHROME
    new Function('localStorage', 'matchMedia', 'navigator', 'document', THEME_SCRIPT)(localStorage, matchMedia, { userAgent: ua, userAgentData: { brands } }, document)
    expect(Object.fromEntries(html)).toEqual({ dark: true, liquid: true })
  })
})
