/**
 * Low model rank (spec 2026-11-15): a US stock in the bottom tenth of the latest run's screener
 * scores. Not the Avoid verdict (a P(beat) rule on watched stocks): it covers every scored US stock.
 */

export const LOW_RANK_LABEL = 'Low model rank'

/** The flag's tooltip and plain explanation; `scored` is how many US stocks the run ranked. */
export function lowRankWhy(scored: number): string {
  return (
    `Bottom 10% of the model’s ranking of ${scored.toLocaleString('en-CA')} US stocks in the latest run. ` +
    'In testing (2021–2026), stocks here trailed the average stock by about 3% over a month and 6% over three months, ' +
    'and more often fell sharply. It is not a sell signal on its own.'
  )
}

/** Migration 0015 not applied yet: the table is missing, so there are no flags rather than an error. */
export function isMissingScreenRanks(error: unknown): boolean {
  if (error === null || typeof error !== 'object') return false
  const { code, message } = error as { code?: unknown; message?: unknown }
  const named = typeof message === 'string' && message.includes('screen_ranks')
  return (code === '42P01' || code === 'PGRST205') && named
}
