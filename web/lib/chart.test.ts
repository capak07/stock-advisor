import { describe, expect, it } from 'vitest'
import { PAD, ease, geometry, indexAt, linePath, resample } from './chart'

describe('geometry', () => {
  const g = geometry(400, 240, [[0, 10], [5, 20]])

  it('pads the value range by 10% and spans the plot', () => {
    expect([g.lo, g.hi]).toEqual([-2, 22])
    expect(g.plotW).toBe(400 - PAD.l - PAD.r)
    expect(g.y(22)).toBe(PAD.t)
    expect(g.y(-2)).toBe(240 - PAD.b)
    expect(g.x(0, 5)).toBe(PAD.l)
    expect(g.x(4, 5)).toBe(PAD.l + g.plotW)
  })

  it('puts grid lines 15%, 50% and 85% of the way down', () => {
    expect(g.ticks.map((t) => +t.toFixed(1))).toEqual([18.4, 10, 1.6])
  })

  it('never draws narrower than 300 px, and survives a flat line', () => {
    const flat = geometry(120, 200, [[5, 5, 5]])
    expect(flat.width).toBe(300)
    expect([flat.lo, flat.hi]).toEqual([4, 6])
  })

  it('draws a path through every point', () => {
    // Plot height 100 − 18 − 26 = 56 over the range −2..22: y(0) = 18 + 56 × 22/24.
    expect(linePath([0, 20], geometry(300, 100, [[0, 20]]))).toBe('M4.0,69.3L238.0,22.7')
  })

  it('finds the point under the pointer', () => {
    expect(indexAt(PAD.l, 5, g)).toBe(0)
    expect(indexAt(PAD.l + g.plotW, 5, g)).toBe(4)
    expect(indexAt(PAD.l + g.plotW + 60, 5, g)).toBeNull()
  })
})

describe('resample', () => {
  it('stretches a line to k points by linear interpolation', () => {
    expect(resample([0, 10], 5)).toEqual([0, 2.5, 5, 7.5, 10])
    expect(resample([3], 3)).toEqual([3, 3, 3])
    expect(resample([1, 2, 3], 3)).toEqual([1, 2, 3])
  })
})

describe('ease', () => {
  it('starts slow, ends slow, and is symmetric', () => {
    expect(ease(0)).toBe(0)
    expect(ease(0.5)).toBe(0.5)
    expect(ease(1)).toBe(1)
    expect(ease(0.25)).toBeCloseTo(1 - ease(0.75))
  })
})
