import { describe, expect, it } from 'vitest'
import { chosenFrom } from './pick-row'

describe('chosenFrom', () => {
  it('maps a row without the new columns to a P pick', () => {
    expect(chosenFrom({})).toEqual({ chosenBy: 'p', scoreRank: null, scoreOf: null })
  })
})
