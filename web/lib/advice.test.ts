import { describe, expect, it } from 'vitest'
import { catalystsLine, costText, describeFactor, factorBars, FACTORS, holdText, tfsaNote } from './advice'

describe('advice text', () => {
  it('labels every model feature', () => {
    const features = ['ret_5', 'ret_21', 'ret_63', 'ret_126', 'mom_12_1', 'rsi_14', 'atr_14_pct', 'vol_20', 'vol_60',
      'dist_52w_high', 'dist_52w_low', 'volume_z', 'gap', 'jump_5d', 'log_adv20', 'ex_bench_21', 'ex_bench_63',
      'ex_sector_21', 'ex_sector_63', 'sector_rank_63', 'rev_growth', 'gross_margin', 'op_margin', 'gross_margin_trend',
      'op_margin_trend', 'eps_growth', 'earnings_yield', 'sales_yield', 'fcf_yield', 'debt_to_equity', 'log_mcap']
    expect(features.filter((f) => !(f in FACTORS))).toEqual([])
  })

  it('describes a factor with its value and the benchmark', () => {
    expect(describeFactor('ex_bench_63', 0.098, 'SPY')).toBe('Return vs SPY over 63 days +9.8%')
    expect(describeFactor('rev_growth', 0.31, 'SPY')).toBe('Revenue growth, year over year +31.0%')
    expect(describeFactor('sector_rank_63', 0.88, 'SPY')).toBe("Sector's 63-day rank 88th percentile")
    expect(describeFactor('ret_21', undefined, 'SPY')).toBe('Return over 21 days')
    expect(describeFactor('mystery', 1, 'SPY')).toBe('mystery')
  })

  it('sizes factor bars by contribution, at most half the bar', () => {
    expect(factorBars([{ feature: 'a', contribution: 0.02 }, { feature: 'b', contribution: -0.01 }])).toEqual([
      { feature: 'a', up: true, width: 50 }, { feature: 'b', up: false, width: 25 },
    ])
  })

  it('says how long to hold and what it costs', () => {
    expect(holdText(10, '2026-10-30')).toBe('~10 trading days · exit by Oct 30')
    expect(holdText(63, '2027-01-19')).toBe('~3 months · exit by Jan 19')
    expect(holdText(126, '2027-04-26')).toBe('~6 months · exit by Apr 26')
    expect(costText('US', 0.031, 1.5)).toBe('3.1% round trip · USD conversion 1.5% each way + spread')
    expect(costText('TSX', 0.001, 1.5)).toBe('0.1% round trip · spread')
    expect(tfsaNote('swing')).toBe('Adds 1 to your TFSA round-trip count')
    expect(tfsaNote('position')).toBe('A long hold keeps TFSA trades low')
  })

  it('names the catalysts inside the hold', () => {
    expect(catalystsLine([])).toBe('No catalysts inside the hold')
    expect(
      catalystsLine([
        { type: 'earnings', date: '2026-10-28' },
        { type: '8-K', date: '2026-10-15', items: ['2.02'] },
      ]),
    ).toBe('Earnings Oct 28, inside the hold · 8-K Oct 15')
    expect(catalystsLine([{ type: 'trial_completion', date: '2026-11-03', exact: false }])).toBe(
      'Phase 2/3 trial completion around Nov 3, inside the hold',
    )
  })
})
