/**
 * Geometry for the Ledger line chart (ported from the mockups' `lineChart`). The SVG is drawn at
 * the container's real width, 1 unit = 1 px, so its 10 px labels stay 10 px on a phone.
 */

export const PAD = { l: 4, r: 62, t: 18, b: 26 } as const
export const MIN_WIDTH = 300
/** Points both windows are resampled to while one morphs into the other. */
export const MORPH_POINTS = 160
/** With a forecast cone, history takes this share of the plot's width and the cone the rest. */
export const HISTORY_SHARE = 0.76

/** A forecast's likely range: fractions of return from the last close. */
export interface ConeQuantiles {
  q10: number
  q50: number
  q90: number
}

export interface Geometry {
  width: number
  height: number
  plotW: number
  plotH: number
  /** The width history is drawn over: all of the plot, or HISTORY_SHARE of it with a cone. */
  histW: number
  /** The width the line is drawn over: all of histW, or a day in progress's share of its session. */
  lineW: number
  lo: number
  hi: number
  /** Three grid lines: 15%, 50% and 85% of the way down. */
  ticks: number[]
  x: (i: number, n: number) => number
  y: (v: number) => number
}

export function geometry(
  width: number,
  height: number,
  lines: readonly (readonly number[])[],
  {
    cone,
    reach = 1,
    baseline,
  }: {
    cone?: ConeQuantiles & { last: number }
    /** The share of the width the line reaches: a 1D chart ends where the session has got to. */
    reach?: number
    /** A level kept on the scale (the previous close of a 1D chart). */
    baseline?: number
  } = {},
): Geometry {
  const w = Math.max(MIN_WIDTH, Math.round(width))
  const plotW = w - PAD.l - PAD.r
  const plotH = height - PAD.t - PAD.b
  const histW = cone ? plotW * HISTORY_SHARE : plotW
  // the cone's ends must fit on the scale too
  const values = [
    ...lines.flat(),
    ...(cone ? [cone.last * (1 + cone.q10), cone.last * (1 + cone.q90)] : []),
    ...(baseline === undefined ? [] : [baseline]),
  ]
  const lineW = histW * Math.min(1, Math.max(0, reach))
  let lo = Math.min(...values)
  let hi = Math.max(...values)
  const pad = (hi - lo) * 0.1 || 1
  lo -= pad
  hi += pad
  return {
    width: w,
    height,
    plotW,
    plotH,
    histW,
    lineW,
    lo,
    hi,
    ticks: [0.15, 0.5, 0.85].map((f) => lo + (hi - lo) * (1 - f)),
    x: (i, n) => PAD.l + (n > 1 ? i / (n - 1) : 0) * lineW,
    y: (v) => PAD.t + (1 - (v - lo) / (hi - lo)) * plotH,
  }
}

export const linePath = (values: readonly number[], g: Geometry): string =>
  values.map((v, i) => `${i ? 'L' : 'M'}${g.x(i, values.length).toFixed(1)},${g.y(v).toFixed(1)}`).join('')

/** Linear resampling to k points, so two windows of different lengths can morph point by point. */
export function resample(values: readonly number[], k: number): number[] {
  if (values.length === k) return [...values]
  if (values.length === 1) return Array.from({ length: k }, () => values[0])
  return Array.from({ length: k }, (_, i) => {
    const x = (i / (k - 1)) * (values.length - 1)
    const lo = Math.floor(x)
    const hi = Math.min(values.length - 1, lo + 1)
    return values[lo] + (values[hi] - values[lo]) * (x - lo)
  })
}

/** The data index under a pointer at `px` (in SVG units), or null outside the line. */
export function indexAt(px: number, n: number, g: Geometry): number | null {
  const i = Math.round(((px - PAD.l) / g.lineW) * (n - 1))
  return i < 0 || i >= n ? null : i
}

/** Ease in and out, as the mockups' tween. */
export const ease = (k: number): number => (k < 0.5 ? 2 * k * k : 1 - (-2 * k + 2) ** 2 / 2)

/** Where the cone is drawn: it opens at the last close and spans the plot's right part to its 10th and 90th percentiles. */
export function coneShape(g: Geometry, last: number, q: ConeQuantiles) {
  const x0 = PAD.l + g.histW
  const y0 = g.y(last)
  const x1 = PAD.l + g.plotW
  const [y10, y50, y90] = [q.q10, q.q50, q.q90].map((f) => g.y(last * (1 + f)))
  return { x0, y0, x1, y10, y50, y90, points: `${x0},${y0} ${x1},${y90} ${x1},${y10}` }
}
