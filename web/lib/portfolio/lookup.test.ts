import { describe, expect, it } from 'vitest'
import { FxRates, PriceBook, onOrBefore } from './lookup'

describe('onOrBefore', () => {
  const days = [{ day: '2026-10-01' }, { day: '2026-10-02' }, { day: '2026-10-05' }]

  it('finds the day itself, else the last day before it', () => {
    expect(onOrBefore(days, '2026-10-02')?.day).toBe('2026-10-02')
    expect(onOrBefore(days, '2026-10-04')?.day).toBe('2026-10-02')
    expect(onOrBefore(days, '2026-12-31')?.day).toBe('2026-10-05')
  })

  it('is null before the first day', () => {
    expect(onOrBefore(days, '2026-09-30')).toBeNull()
    expect(onOrBefore([], '2026-10-01')).toBeNull()
  })
})

describe('FxRates', () => {
  const fx = new FxRates([
    { day: '2026-10-02', usdCad: 1.37 },
    { day: '2026-10-01', usdCad: 1.36 },
  ])

  it('sorts its rates and carries the last one forward', () => {
    expect(fx.on('2026-10-04')).toBe(1.37)
    expect(fx.latest()).toEqual({ day: '2026-10-02', usdCad: 1.37 })
  })

  it('converts USD closes and leaves CAD closes alone', () => {
    expect(fx.toCad({ day: '2026-10-01', close: 100, currency: 'USD' })).toBeCloseTo(136)
    expect(fx.toCad({ day: '2026-10-01', close: 100, currency: 'CAD' })).toBe(100)
    expect(fx.toCad({ day: '2026-09-01', close: 100, currency: 'USD' })).toBeNull()
  })
})

describe('PriceBook', () => {
  const book = new PriceBook(
    new Map([
      [
        'stock:SPY',
        [
          { day: '2026-10-02', close: 510, currency: 'USD' as const },
          { day: '2026-10-01', close: 500, currency: 'USD' as const },
        ],
      ],
    ]),
  )

  it('carries a close forward over days without one', () => {
    expect(book.on('stock:SPY', '2026-10-03')?.close).toBe(510)
    expect(book.latest('stock:SPY')?.day).toBe('2026-10-02')
    expect(book.days('stock:SPY')).toEqual(['2026-10-01', '2026-10-02'])
  })

  it('knows nothing about an asset without closes', () => {
    expect(book.on('stock:XIU.TO', '2026-10-03')).toBeNull()
    expect(book.latest('crypto:BTC')).toBeNull()
  })
})
