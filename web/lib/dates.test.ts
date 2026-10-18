import { describe, expect, it } from 'vitest'
import { timeOrDate } from './dates'

describe('timeOrDate', () => {
  it("shows today's time alone and an earlier day's with its date, on Toronto's clock", () => {
    const now = new Date('2026-10-16T20:00:00Z')
    expect(timeOrDate('2026-10-16T18:53:00Z', now)).toMatch(/^2:53\sp\.m\.$/)
    expect(timeOrDate('2026-10-15T21:53:00Z', now)).toMatch(/^Oct 15, 5:53\sp\.m\.$/)
    expect(timeOrDate('2026-10-16T03:30:00Z', now)).toMatch(/^Oct 15, 11:30\sp\.m\.$/) // still Oct 15 in Toronto
  })
})
