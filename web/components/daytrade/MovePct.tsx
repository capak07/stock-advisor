import { fmtMove } from '@/lib/format'

/**
 * Under a level's figure: how far it is from the entry, "+4.7%" or "−2.4%". With no `to` it holds the line
 * empty, so the entry's tile keeps its figure level with the target's and the stop's.
 */
export function MovePct({ from, to, tone }: { from: number; to?: number; tone?: 'gain' | 'loss' }) {
  if (to === undefined) {
    return (
      <span className="lvl-pct" aria-hidden="true">
        {' '}
      </span>
    )
  }
  return <span className={`lvl-pct num ${tone ?? ''}`.trim()}>{fmtMove(from, to)}</span>
}
