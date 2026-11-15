import { LOW_RANK_LABEL, lowRankWhy } from '@/lib/low-rank'

/** The Low model rank badge; its explanation is the tooltip and the accessible description. */
export function LowRankChip({ scored }: { scored: number }) {
  const why = lowRankWhy(scored)
  return (
    <span className="chip low-rank" title={why} aria-label={`${LOW_RANK_LABEL}. ${why}`}>
      {LOW_RANK_LABEL}
    </span>
  )
}
