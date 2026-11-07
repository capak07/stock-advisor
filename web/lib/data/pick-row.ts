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

/** The active model's picks backtest (`metrics.backtest.all`), as a pick shows it. */
export interface TrackRecord {
  picks: number
  meanNetPct: number
  beatRate: number
}

/** Null when the record is missing, has no picks, or a number is missing. */
export function trackRecordFrom(metrics: unknown): TrackRecord | null {
  const all = (metrics as { backtest?: { all?: Record<string, unknown> } } | null)?.backtest?.all
  if (!all) return null
  const picks = all.picks
  const net = all.mean_net_pct
  const beat = all.beat_rate
  if (typeof picks !== 'number' || picks <= 0) return null
  if (typeof net !== 'number' || !Number.isFinite(net) || typeof beat !== 'number' || !Number.isFinite(beat)) return null
  return { picks, meanNetPct: net, beatRate: beat }
}
