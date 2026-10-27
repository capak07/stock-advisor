import { describe, expect, it } from 'vitest'
import { addDays, daysBetween, longDay, shortDay, todayInToronto } from './dates'
import { fmtAmount, fmtMoney, fmtPct, fmtPrice, fmtQty } from './format'

describe('formats', () => {
  it('writes percentages with a sign and a real minus', () => {
    expect(fmtPct(6)).toBe('+6.0%')
    expect(fmtPct(-16.14)).toBe('−16.1%')
    expect(fmtPct(-0.04)).toBe('0.0%')
  })

  it('writes money in en-CA with an optional sign', () => {
    expect(fmtMoney(34237.4)).toBe('C$34,237')
    expect(fmtMoney(-405)).toBe('−C$405')
    expect(fmtMoney(1950, { signed: true })).toBe('+C$1,950')
    expect(fmtMoney(-0.2, { signed: true })).toBe('C$0')
    expect(fmtAmount(-405, { signed: true })).toBe('−405')
  })

  it('writes prices in their currency and quantities without trailing zeros', () => {
    expect(fmtPrice(163.4, 'USD')).toBe('US$163.40')
    expect(fmtPrice(0.4321, 'CAD')).toBe('C$0.4321')
    expect(fmtPrice(12.3, 'CAD')).toBe('C$12.30')
    expect(fmtPrice(0.5, 'USD')).toBe('US$0.5000')
    // a coin worth a fraction of a cent keeps 4 significant figures, never an exponent
    expect(fmtPrice(2.5e-6, 'USD')).toBe('US$0.000002500')
    expect(fmtPrice(0.00001234, 'CAD')).toBe('C$0.00001234')
    expect(fmtQty(10)).toBe('10')
    expect(fmtQty(0.12345678)).toBe('0.12345678')
  })
})

describe('dates', () => {
  it('shifts and compares ISO days', () => {
    expect(addDays('2026-10-16', 30)).toBe('2026-11-15')
    expect(addDays('2026-03-01', -1)).toBe('2026-02-28')
    expect(daysBetween('2026-09-02', '2026-09-12')).toBe(10)
  })

  it('writes short and long days', () => {
    expect(shortDay('2026-10-16')).toBe('Oct 16')
    expect(longDay('2025-05-12')).toBe('May 12, 2025')
  })

  it("gives today's date in Toronto", () => {
    // 02:30 UTC on Oct 17 is still Oct 16 in Toronto (EDT, UTC−4).
    expect(todayInToronto(new Date('2026-10-17T02:30:00Z'))).toBe('2026-10-16')
  })
})
