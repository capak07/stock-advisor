import { PICK_P_FLOOR } from '@/lib/today'

/** The picks' bar as the pages word it: "58%". */
export const PICK_BAR = `${Math.round(PICK_P_FLOOR * 100)}%`

/**
 * Why a run picked nothing, worded the same on Today's Picks card and the Picks page: "The best
 * chance of beating the market was US 52.7% vs SPY; a pick needs 58%. Nothing has enough evidence
 * to buy." Without a best-chance line (a run with no forecasts) only the last sentence. The best
 * chance is a fact about the run, never shown on a pick card.
 */
export function NoPicksSentence({ bestChance }: { bestChance: string | null }) {
  return (
    <>
      {bestChance !== null && (
        <>
          The best chance of beating the market was <span className="num">{bestChance}</span>; a pick needs {PICK_BAR}.{' '}
        </>
      )}
      Nothing has enough evidence to buy.
    </>
  )
}
