/**
 * Migration 0014 not applied yet: `daytrade_signals.skill_rank` does not exist, so a query naming it
 * fails (Postgres 42703, "column daytrade_signals.skill_rank does not exist"). The Day trade page then
 * reads without it (every skill rank null: an empty skill list) instead of erroring.
 */
export function isMissingSkillRank(error: unknown): boolean {
  if (error === null || typeof error !== 'object') return false
  const { code, message } = error as { code?: unknown; message?: unknown }
  return code === '42703' || (typeof message === 'string' && message.includes('skill_rank'))
}

/** `query`, or `fallback` (the same query without `skill_rank`) when the column is missing. */
export async function withoutSkillRankIfMissing<T>(query: () => Promise<T>, fallback: () => Promise<T>): Promise<T> {
  try {
    return await query()
  } catch (error) {
    if (!isMissingSkillRank(error)) throw error
    return fallback()
  }
}
