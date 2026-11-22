const W = 320
const H = 84
const PAD = 6

/**
 * A small line of `values` (and a dashed `compare` line on the same scale), drawn left to right
 * (`.draw` in ledger.css; reduced motion shows it at once). No axes: a glance, not a chart. Null with
 * fewer than two points.
 */
export function Sparkline({ values, compare, label }: { values: number[]; compare?: number[]; label: string }) {
  if (values.length < 2) return null
  const other = compare && compare.length >= 2 ? compare : null
  const all = other ? [...values, ...other] : values
  const min = Math.min(...all)
  const max = Math.max(...all)
  const span = max - min || 1
  const path = (series: number[]) =>
    series
      .map((v, i) => {
        const x = (i / (series.length - 1)) * W
        const y = PAD + (1 - (v - min) / span) * (H - 2 * PAD)
        return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)} ${y.toFixed(1)}`
      })
      .join(' ')
  const line = path(values)
  return (
    <svg className="spark draw" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label={label}>
      <path className="cone" d={`${line} L${W} ${H} L0 ${H}Z`} fill="var(--chart-1)" fillOpacity={0.1} stroke="none" />
      {other && (
        <path
          d={path(other)}
          fill="none"
          stroke="var(--chart-3)"
          strokeWidth={1.5}
          strokeDasharray="4 4"
          opacity={0.9}
          vectorEffect="non-scaling-stroke"
        />
      )}
      <path
        className="line"
        d={line}
        fill="none"
        stroke="var(--chart-1)"
        strokeWidth={2.2}
        strokeLinejoin="round"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  )
}
