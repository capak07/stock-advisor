import type { CSSProperties } from 'react'
import { fmtPct } from '@/lib/format'

/**
 * The design's wide range bar: q10 to q90 around the median, with a zero line. The scale is
 * ±`span` points, at least 10 and wide enough for this range. Quantiles are fractions.
 */
export function RangeBar({ q10, q50, q90, benchmark }: { q10: number; q50: number; q90: number; benchmark: string }) {
  const span = Math.max(10, Math.ceil(Math.max(Math.abs(q10), Math.abs(q90)) * 100) + 2)
  const pos = (v: number) => Math.max(0, Math.min(100, 50 + ((v * 100) / span) * 50))
  const [left, mid, right] = [pos(q10), pos(q50), pos(q90)]
  const origin = right > left ? ((mid - left) / (right - left)) * 100 : 50
  const text = `Likely range relative to ${benchmark}: q10 ${fmtPct(q10 * 100)}, median ${fmtPct(q50 * 100)}, q90 ${fmtPct(q90 * 100)}`
  return (
    <div className="range wide" role="img" aria-label={text} title={text} style={{ marginTop: 4 }}>
      <div className="track" />
      <div className="zero" style={{ left: '50%' }} />
      <div className="band" style={{ left: `${left}%`, width: `${right - left}%`, '--origin': `${origin}%` } as CSSProperties} />
      <div className="mid" style={{ left: `${mid}%` }} />
    </div>
  )
}
