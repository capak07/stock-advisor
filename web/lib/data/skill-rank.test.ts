import { describe, expect, it, vi } from 'vitest'
import { isMissingSkillRank, withoutSkillRankIfMissing } from './skill-rank'

const MISSING = new Error('column daytrade_signals.skill_rank does not exist')

describe('the skill_rank fallback (migration 0014 not applied yet)', () => {
  it('knows the missing-column error by its code or by naming the column', () => {
    expect(isMissingSkillRank(MISSING)).toBe(true)
    expect(isMissingSkillRank({ code: '42703', message: 'column does not exist' })).toBe(true)
    expect(isMissingSkillRank(new Error('failed to parse logic tree ((skill_rank.not.is.null,best_rank.not.is.null))'))).toBe(true)
    expect(isMissingSkillRank(new Error('JWT expired'))).toBe(false)
    expect(isMissingSkillRank(null)).toBe(false)
  })

  it('runs the query without skill_rank when the column is missing', async () => {
    const fallback = vi.fn(async () => ['old'])
    await expect(withoutSkillRankIfMissing(async () => Promise.reject(MISSING), fallback)).resolves.toEqual(['old'])
    expect(fallback).toHaveBeenCalledOnce()
  })

  it('keeps the first answer, and any other error', async () => {
    const fallback = vi.fn(async () => ['old'])
    await expect(withoutSkillRankIfMissing(async () => ['new'], fallback)).resolves.toEqual(['new'])
    await expect(withoutSkillRankIfMissing(async () => Promise.reject(new Error('JWT expired')), fallback)).rejects.toThrow('JWT expired')
    expect(fallback).not.toHaveBeenCalled()
  })
})
