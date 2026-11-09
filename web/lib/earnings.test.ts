import { describe, expect, it } from 'vitest'
import { changes, margins, type Quarter, ttm, yearAgo } from './earnings'

const q = (periodEnd: string, o: Partial<Quarter> = {}): Quarter => ({
  periodEnd, fiscalPeriod: null, revenue: 100, grossProfit: 40, operatingIncome: 20, netIncome: 10, epsDiluted: 1, ...o,
})

describe('yearAgo', () => {
  it('finds the quarter a year earlier', () => {
    const all = [q('2025-06-30'), q('2024-06-30'), q('2025-03-31')]
    expect(yearAgo(all[0], all)?.periodEnd).toBe('2024-06-30')
  })

  it('matches a September fiscal year within 10 days', () => {
    const all = [q('2025-09-27'), q('2024-09-28'), q('2024-06-29')]
    expect(yearAgo(all[0], all)?.periodEnd).toBe('2024-09-28')
  })

  it('returns null when nothing is close to a year earlier', () => {
    const all = [q('2025-06-30'), q('2024-03-31'), q('2025-03-31')]
    expect(yearAgo(all[0], all)).toBeNull()
  })
})

describe('margins', () => {
  it('divides by revenue', () => {
    expect(margins(q('2025-06-30'))).toEqual({ gross: 0.4, operating: 0.2, net: 0.1 })
  })

  it('is null for a missing part or no revenue', () => {
    expect(margins(q('2025-06-30', { grossProfit: null }))).toEqual({ gross: null, operating: 0.2, net: 0.1 })
    expect(margins(q('2025-06-30', { revenue: null }))).toEqual({ gross: null, operating: null, net: null })
    expect(margins(q('2025-06-30', { revenue: 0 }))).toEqual({ gross: null, operating: null, net: null })
  })
})

describe('ttm', () => {
  const five = [q('2025-12-31'), q('2025-09-30'), q('2025-06-30'), q('2025-03-31'), q('2024-12-31')]

  it('sums the newest four quarters', () => {
    expect(ttm(five)).toEqual({ revenue: 400, grossProfit: 160, operatingIncome: 80, netIncome: 40, epsDiluted: 4 })
  })

  it('is null with fewer than four quarters', () => {
    expect(ttm(five.slice(0, 3))).toBeNull()
  })

  it('is null when a quarter is missing and the span is too long', () => {
    expect(ttm([q('2025-12-31'), q('2025-09-30'), q('2025-03-31'), q('2024-12-31')])).toBeNull()
  })

  it('has a null sum when any quarter lacks the metric', () => {
    const all = [q('2025-12-31', { epsDiluted: null }), ...five.slice(1)]
    expect(ttm(all)?.epsDiluted).toBeNull()
    expect(ttm(all)?.revenue).toBe(400)
  })
})

describe('changes', () => {
  it('is empty without a year-ago quarter', () => {
    expect(changes([q('2025-06-30')])).toEqual([])
  })

  it('describes revenue, operating margin and EPS', () => {
    const all = [
      q('2025-06-30', { revenue: 112, operatingIncome: 20.16, epsDiluted: 1.42 }),
      q('2024-06-30', { revenue: 100, operatingIncome: 16, epsDiluted: 1.1 }),
    ]
    expect(changes(all)).toEqual([
      'Revenue up 12% on the same quarter a year earlier',
      'Operating margin 18.0%, up 2.0 points',
      'Diluted EPS $1.42, up from $1.10',
    ])
  })

  it('says down, and falls back to gross margin', () => {
    const all = [
      q('2025-06-30', { revenue: 90, operatingIncome: null, grossProfit: 36, epsDiluted: 0.5 }),
      q('2024-06-30', { revenue: 100, operatingIncome: null, grossProfit: 45, epsDiluted: 1 }),
    ]
    expect(changes(all)).toEqual([
      'Revenue down 10% on the same quarter a year earlier',
      'Gross margin 40.0%, down 5.0 points',
      'Diluted EPS $0.50, down from $1.00',
    ])
  })

  it('skips a zero or null base', () => {
    const all = [
      q('2025-06-30', { revenue: 110, operatingIncome: 22, epsDiluted: 2 }),
      q('2024-06-30', { revenue: 0, operatingIncome: 0, epsDiluted: null }),
    ]
    expect(changes(all)).toEqual([])
  })

  it('skips a margin that moved under a point', () => {
    const all = [
      q('2025-06-30', { revenue: 100, operatingIncome: 20.5, grossProfit: null, netIncome: null }),
      q('2024-06-30', { revenue: 100, operatingIncome: 20, grossProfit: null, netIncome: null }),
    ]
    expect(changes(all)).toEqual([])
  })

  it('writes a negative-to-positive EPS', () => {
    const all = [q('2025-06-30', { epsDiluted: 0.2 }), q('2024-06-30', { epsDiluted: -0.1 })]
    expect(changes(all)).toContain('Diluted EPS $0.20, up from -$0.10')
  })
})
