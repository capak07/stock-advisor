'use client'

import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { MORPH_POINTS, PAD, coneShape, ease, geometry, indexAt, linePath, resample, type ConeQuantiles } from '@/lib/chart'
import { fmtPct } from '@/lib/format'

export interface Benchmark {
  values: number[]
  color: string
}

/** A forecast drawn past the last close: its likely range as fractions of return, and what it means. */
export interface Cone extends ConeQuantiles {
  label: string
  /** A shorter label for narrow charts. */
  short?: string
}

interface Drawn {
  series: number[]
  benchmarks: Benchmark[]
  dates: string[]
}

/**
 * The Ledger line chart (the mockups' `lineChart`). The main line draws in over 600 ms, benchmark
 * lines fade in, and a new window of data morphs from the old one over 250 ms. Hovering shows the
 * day and value under the pointer. An optional forecast cone opens from the last close over the
 * right quarter of the plot, and morphs to another horizon's range over 300 ms.
 */
export function LineChart({
  series,
  dates,
  benchmarks = [],
  height = 240,
  format = (v) => v.toFixed(2),
  label,
  cone,
}: {
  series: number[]
  dates: string[]
  benchmarks?: Benchmark[]
  height?: number
  format?: (value: number) => string
  label: string
  cone?: Cone
}) {
  const box = useRef<HTMLDivElement>(null)
  const mainLine = useRef<SVGPathElement>(null)
  const lastWidth = useRef<number | null>(null)
  const shown = useRef<Drawn>({ series, benchmarks, dates })
  const [width, setWidth] = useState<number | null>(null)
  const [intro, setIntro] = useState(true)
  const [drawn, setDrawn] = useState<Drawn>(shown.current)
  const [hover, setHover] = useState<number | null>(null)
  const [shownCone, setShownCone] = useState<Cone | undefined>(cone)
  const coneShown = useRef<Cone | undefined>(cone)

  // Measure before the first paint, so the line draws in once, at the real width. A later
  // resize redraws without the intro.
  useLayoutEffect(() => {
    const el = box.current
    if (!el) return
    const measure = () => {
      const w = el.clientWidth
      if (lastWidth.current !== null && Math.round(lastWidth.current) !== Math.round(w)) setIntro(false)
      lastWidth.current = w
      setWidth(w)
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  // The draw-in animation needs the main line's length.
  useLayoutEffect(() => {
    if (intro && mainLine.current) {
      mainLine.current.style.setProperty('--len', String(Math.ceil(mainLine.current.getTotalLength())))
    }
  }, [intro, width])

  useEffect(() => {
    shown.current = drawn
  }, [drawn])

  // A new window of data morphs from the one on screen.
  useEffect(() => {
    const from = shown.current
    if (from.series === series && from.benchmarks === benchmarks && from.dates === dates) return
    const target: Drawn = { series, benchmarks, dates }
    let frame = 0
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) {
      frame = requestAnimationFrame(() => {
        setIntro(false)
        setDrawn(target)
      })
      return () => cancelAnimationFrame(frame)
    }
    const fromS = resample(from.series, MORPH_POINTS)
    const toS = resample(series, MORPH_POINTS)
    const fromB = benchmarks.map((b, j) => resample(from.benchmarks[j]?.values ?? b.values, MORPH_POINTS))
    const toB = benchmarks.map((b) => resample(b.values, MORPH_POINTS))
    const morphDates = resample(dates.map((_, i) => i), MORPH_POINTS).map((x) => dates[Math.round(x)])
    const start = performance.now()
    frame = requestAnimationFrame(function step(now) {
      const k = Math.min(1, (now - start) / 250)
      const e = ease(k)
      setIntro(false)
      if (k < 1) {
        setDrawn({
          series: fromS.map((v, i) => v + (toS[i] - v) * e),
          benchmarks: benchmarks.map((b, j) => ({ ...b, values: fromB[j].map((v, i) => v + (toB[j][i] - v) * e) })),
          dates: morphDates,
        })
        frame = requestAnimationFrame(step)
      } else {
        setDrawn(target)
      }
    })
    return () => cancelAnimationFrame(frame)
  }, [series, benchmarks, dates])

  useEffect(() => {
    coneShown.current = shownCone
  }, [shownCone])

  // Another horizon's range morphs from the one on screen.
  useEffect(() => {
    const from = coneShown.current
    if (from === cone) return
    let frame = 0
    if (!from || !cone || matchMedia('(prefers-reduced-motion: reduce)').matches) {
      frame = requestAnimationFrame(() => setShownCone(cone))
      return () => cancelAnimationFrame(frame)
    }
    const start = performance.now()
    frame = requestAnimationFrame(function step(now) {
      const k = Math.min(1, (now - start) / 300)
      const e = ease(k)
      const mix = (a: number, b: number) => a + (b - a) * e
      setShownCone(k < 1 ? { ...cone, q10: mix(from.q10, cone.q10), q50: mix(from.q50, cone.q50), q90: mix(from.q90, cone.q90) } : cone)
      if (k < 1) frame = requestAnimationFrame(step)
    })
    return () => cancelAnimationFrame(frame)
  }, [cone])

  const n = drawn.series.length
  const last = drawn.series[n - 1]
  const g =
    width === null || n < 2
      ? null
      : geometry(width, height, [drawn.series, ...drawn.benchmarks.map((b) => b.values)], {
          cone: shownCone ? { last, ...shownCone } : undefined,
        })
  const c = g && shownCone ? coneShape(g, last, shownCone) : null

  const onMove = (event: React.PointerEvent<SVGSVGElement>) => {
    if (!g) return
    const rect = event.currentTarget.getBoundingClientRect()
    setHover(indexAt(((event.clientX - rect.left) / rect.width) * g.width, n, g))
  }

  const hx = g && hover !== null ? g.x(hover, n) : 0
  const hy = g && hover !== null ? g.y(drawn.series[hover]) : 0
  // The SVG is scaled down only when the box is narrower than the 300 px minimum.
  const scale = g && width ? width / g.width : 1
  return (
    <div ref={box} className="chart">
      {g && (
        <svg
          role="img"
          aria-label={label}
          viewBox={`0 0 ${g.width} ${height}`}
          onPointerMove={onMove}
          onPointerLeave={() => setHover(null)}
        >
          <g className="grid">
            {g.ticks.map((v) => (
              <g key={v}>
                <line x1={PAD.l} x2={c ? g.width - 4 : PAD.l + g.plotW} y1={g.y(v)} y2={g.y(v)} />
                {/* with a cone, its labels use the right edge, so price ticks sit on the left above their lines */}
                {c ? (
                  <text x={PAD.l + 2} y={g.y(v) - 5}>
                    {format(v)}
                  </text>
                ) : (
                  <text x={g.width - 4} y={g.y(v) + 3} textAnchor="end">
                    {format(v)}
                  </text>
                )}
              </g>
            ))}
          </g>
          {drawn.benchmarks.map((b, j) => (
            <path
              key={j}
              d={linePath(b.values, g)}
              fill="none"
              stroke={b.color}
              strokeWidth={1.6}
              strokeLinejoin="round"
              className={intro ? 'late' : undefined}
            />
          ))}
          {c && shownCone && (
            <g aria-label={`Forecast: ${shownCone.label}`}>
              <polygon
                className={intro ? 'cone forecast-cone' : 'forecast-cone'}
                points={c.points}
                fill="var(--chart-5)"
                style={{ transformOrigin: `${c.x0}px ${c.y0}px` }}
              />
              <path
                className={intro ? 'cone' : undefined}
                d={`M${c.x0},${c.y0}L${c.x1},${c.y50}`}
                stroke="var(--chart-4)"
                strokeWidth={1.6}
                strokeDasharray="5 4"
                style={{ transformOrigin: `${c.x0}px ${c.y0}px` }}
              />
              <g className={intro ? 'late' : undefined}>
                <text x={c.x1 + 4} y={c.y90 + 3} style={{ fill: 'var(--gain)' }}>
                  {fmtPct(shownCone.q90 * 100)}
                </text>
                <text x={c.x1 + 4} y={c.y50 + 3}>
                  {fmtPct(shownCone.q50 * 100)}
                </text>
                <text x={c.x1 + 4} y={c.y10 + 3} style={{ fill: 'var(--loss)' }}>
                  {fmtPct(shownCone.q10 * 100)}
                </text>
                <text x={c.x1} y={height - 6} textAnchor="end">
                  {(g.width < 560 ? shownCone.short : undefined) ?? shownCone.label}
                </text>
              </g>
            </g>
          )}
          <path
            ref={mainLine}
            d={linePath(drawn.series, g)}
            fill="none"
            stroke="var(--chart-1)"
            strokeWidth={2}
            strokeLinejoin="round"
            strokeLinecap="round"
            className={intro ? 'draw main-line' : 'main-line'}
          />
          <circle
            cx={g.x(n - 1, n)}
            cy={g.y(drawn.series[n - 1])}
            r={4}
            fill="var(--chart-1)"
            stroke="var(--card)"
            strokeWidth={2}
          />
          <text x={PAD.l} y={height - 6}>
            {drawn.dates[0]}
          </text>
          <text x={g.x(n - 1, n)} y={height - 6} textAnchor={c ? 'middle' : 'end'}>
            {c ? 'today' : drawn.dates[n - 1]}
          </text>
          <line
            x1={hx}
            x2={hx}
            y1={PAD.t}
            y2={PAD.t + g.plotH}
            stroke="var(--muted-foreground)"
            strokeDasharray="3 3"
            opacity={hover === null ? 0 : 0.6}
          />
          <circle cx={hx} cy={hy} r={4} fill="var(--chart-1)" opacity={hover === null ? 0 : 1} />
        </svg>
      )}
      {g && width !== null && hover !== null && (
        <div
          className="tip show"
          style={{
            left: Math.min(width - 150, Math.max(0, hx * scale - 60)),
            top: Math.max(0, hy * scale - 44),
          }}
        >
          <span className="muted">{drawn.dates[hover]}</span>{' '}
          <span className="num" style={{ fontWeight: 600 }}>
            {format(drawn.series[hover])}
          </span>
        </div>
      )}
    </div>
  )
}
