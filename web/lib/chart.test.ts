import { describe, expect, it } from 'vitest'
import { PAD, coneShape, ease, geometry, indexAt, linePath, resample } from './chart'

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

describe('the forecast cone', () => {
  // history 0..10, last close 10; a cone of −10%..+20% around a +5% median
  const q = { q10: -0.1, q50: 0.05, q90: 0.2 }
  const g = geometry(400, 240, [[0, 10]], { cone: { last: 10, ...q } })

  it('leaves the right quarter of the plot for the cone, and scales to its ends', () => {
    expect(g.histW).toBeCloseTo(g.plotW * 0.76)
    expect(g.x(1, 2)).toBeCloseTo(PAD.l + g.plotW * 0.76)
    expect(g.hi).toBeCloseTo(12 + 1.2) // the +20% end, 12, plus 10% of the 0..12 range
    expect(indexAt(PAD.l + g.histW, 50, g)).toBe(49) // the last close
    expect(indexAt(PAD.l + g.plotW, 50, g)).toBeNull() // the cone isn't history
  })

  it('opens from the last close to the 10th and 90th percentiles, with the median between', () => {
    const c = coneShape(g, 10, q)
    expect([c.x0, c.y0]).toEqual([g.x(1, 2), g.y(10)])
    expect(c.x1).toBeCloseTo(PAD.l + g.plotW)
    expect([c.y10, c.y50, c.y90]).toEqual([g.y(9), g.y(10.5), g.y(12)])
    expect(c.points).toBe(`${c.x0},${c.y0} ${c.x1},${c.y90} ${c.x1},${c.y10}`)
  })

  it('without a cone, history spans the whole plot', () => {
    const plain = geometry(400, 240, [[0, 10]])
    expect(plain.histW).toBe(plain.plotW)
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
