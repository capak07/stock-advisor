import { describe, expect, it } from 'vitest'
import { supportsLiquidGlass } from './glass'

describe('supportsLiquidGlass', () => {
  it('is true for Chrome, Edge and the Android WebView', () => {
    expect(supportsLiquidGlass([{ brand: 'Chromium' }, { brand: 'Google Chrome' }], '')).toBe(true)
    expect(supportsLiquidGlass([{ brand: 'Microsoft Edge' }, { brand: 'Chromium' }], '')).toBe(true)
    expect(supportsLiquidGlass(undefined, 'Mozilla/5.0 (Linux; Android 14; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/131.0 Mobile Safari/537.36')).toBe(true)
  })
  it('is false for Firefox, Safari and Chrome on iOS (WebKit underneath)', () => {
    expect(supportsLiquidGlass(undefined, 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0')).toBe(false)
    expect(supportsLiquidGlass(undefined, 'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15')).toBe(false)
    expect(supportsLiquidGlass(undefined, 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/131.0 Mobile/15E148 Safari/604.1')).toBe(false)
  })
})
