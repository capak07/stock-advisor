import { describe, expect, it } from 'vitest'
import { isMissingScreenRanks, LOW_RANK_LABEL, lowRankWhy } from './low-rank'

describe('low model rank', () => {
  it('names the flag apart from the Avoid verdict', () => {
    expect(LOW_RANK_LABEL).toBe('Low model rank')
    expect(LOW_RANK_LABEL.toLowerCase()).not.toContain('avoid')
  })

  it('explains the flag with the size of the ranking and what testing showed', () => {
    const why = lowRankWhy(3712)
    expect(why).toContain('Bottom 10% of the model’s ranking of 3,712 US stocks')
    expect(why).toContain('about 3% over a month and 6% over three months')
    expect(why).toContain('not a sell signal on its own')
  })

  it('reads a missing table (migration 0015 not applied) as no flags, and nothing else', () => {
    expect(isMissingScreenRanks({ code: '42P01', message: 'relation "public.screen_ranks" does not exist' })).toBe(true)
    expect(isMissingScreenRanks({ code: 'PGRST205', message: "Could not find the table 'public.screen_ranks' in the schema cache" })).toBe(true)
    expect(isMissingScreenRanks({ code: '42501', message: 'permission denied for table screen_ranks' })).toBe(false)
    expect(isMissingScreenRanks(null)).toBe(false)
  })
})
