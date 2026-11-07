import { describe, expect, it } from 'vitest'
import { chosenFrom, trackRecordFrom } from './pick-row'

describe('chosenFrom', () => {
  it('maps a row without the new columns to a P pick', () => {
    expect(chosenFrom({})).toEqual({ chosenBy: 'p', scoreRank: null, scoreOf: null })
  })
})

describe('trackRecordFrom', () => {
  it('reads the model backtest', () => {
    expect(trackRecordFrom({ backtest: { all: { picks: 648, mean_net_pct: 1.73, beat_rate: 0.47 } } })).toEqual({
      picks: 648,
      meanNetPct: 1.73,
      beatRate: 0.47,
    })
  })

  it('is null with no picks, a null number, or no record', () => {
    expect(trackRecordFrom({ backtest: { all: { picks: 0, mean_net_pct: null, beat_rate: null } } })).toBeNull()
    expect(trackRecordFrom({ backtest: { all: { picks: 40, mean_net_pct: null, beat_rate: 0.4 } } })).toBeNull()
    expect(trackRecordFrom({})).toBeNull()
  })
})
