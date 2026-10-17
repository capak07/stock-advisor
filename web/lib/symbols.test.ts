import { describe, expect, it } from 'vitest'
import { isValidSymbol, marketOf, normalizeSymbol, tradeCurrency } from './symbols'

describe('symbols', () => {
  it("normalizes case, spaces and a dotted TSX class to Yahoo's form", () => {
    expect(normalizeSymbol('  ry.to ')).toBe('RY.TO')
    expect(normalizeSymbol('rci.b.to')).toBe('RCI-B.TO')
    expect(normalizeSymbol('brk.b')).toBe('BRK.B')
  })

  it("accepts the database's formats and nothing else", () => {
    for (const ok of ['AAPL', 'BRK.B', 'RY.TO', 'RCI-B.TO', 'REI-UN.TO']) expect(isValidSymbol(ok, 'stock')).toBe(true)
    for (const bad of ['', 'TOOLONG', 'RY.VN', 'BRK.BB', 'RY-.TO']) expect(isValidSymbol(bad, 'stock')).toBe(false)
    expect(isValidSymbol('BTC', 'crypto')).toBe(true)
    expect(isValidSymbol('1INCH', 'crypto')).toBe(true)
    expect(isValidSymbol('B', 'crypto')).toBe(false)
  })

  it('places a stock in its market and its trade currency', () => {
    expect(marketOf('RY.TO')).toBe('TSX')
    expect(marketOf('BRK.B')).toBe('US')
    expect(tradeCurrency('stock', 'AAPL')).toBe('USD')
    expect(tradeCurrency('stock', 'RY.TO')).toBe('CAD')
    expect(tradeCurrency('crypto', 'BTC')).toBe('CAD')
  })
})
