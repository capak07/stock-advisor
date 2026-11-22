import { describe, expect, it } from 'vitest'
import type { ForecastHorizon } from './data/ticker'
import { edgeWords, nearestHorizon, outlookFor } from './outlook'

const h = (horizon: number): ForecastHorizon => ({ horizon, q10: -0.05, q50: 0.01, q90: 0.06, pBeat: 0.52 })

describe('nearestHorizon', () => {
  it('picks 21, else the closest, ties to the shorter', () => {
    expect(nearestHorizon([5, 10, 20, 21, 63])).toBe(21)
    expect(nearestHorizon([7, 14, 30, 90])).toBe(14)
    expect(nearestHorizon([18, 24])).toBe(18)
    expect(nearestHorizon([])).toBeNull()
  })

  it('takes another target', () => {
    expect(nearestHorizon([5, 21, 63], 60)).toBe(63)
    expect(nearestHorizon([63, 5, 21], 10)).toBe(5) // order does not matter
  })
})

describe('outlookFor', () => {
  it('uses the verdict horizon when the run has it', () => {
    expect(outlookFor([h(21), h(63)], 63)?.horizon).toBe(63)
    expect(outlookFor([h(21), h(63)], 10)?.horizon).toBe(21)
  })

  it('falls back to 21 or the closest without a verdict horizon, and is null without rows', () => {
    expect(outlookFor([h(5), h(21), h(63)], null)?.horizon).toBe(21)
    expect(outlookFor([h(5), h(10)], null)?.horizon).toBe(10)
    expect(outlookFor([], 21)).toBeNull()
  })
})

describe('edgeWords', () => {
  it('words the edge plainly', () => {
    expect(edgeWords('buy')).toBe('Buy')
    expect(edgeWords('avoid')).toBe('Avoid')
    expect(edgeWords('hold')).toBe('No clear edge')
    expect(edgeWords(null)).toBe('No clear edge')
  })
})
