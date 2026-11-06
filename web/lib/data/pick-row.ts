/** How a stored pick was chosen. A row from before migration 0011 has none of these columns. */

export interface ChosenFields {
  chosenBy: 'p' | 'rank'
  scoreRank: number | null
  scoreOf: number | null
}

const whole = (value: unknown): number | null => {
  const n = typeof value === 'string' ? Number(value) : value
  return typeof n === 'number' && Number.isInteger(n) ? n : null
}

/** `chosen_by` / `score_rank` / `score_of`. Missing values are a P pick with no place. */
export function chosenFrom(row: { chosen_by?: unknown; score_rank?: unknown; score_of?: unknown }): ChosenFields {
  return {
    chosenBy: row.chosen_by === 'rank' ? 'rank' : 'p',
    scoreRank: whole(row.score_rank),
    scoreOf: whole(row.score_of),
  }
}
