import { describe, expect, it } from 'vitest'
import { IMPORTANT_ITEMS, isImportant, ITEM_LABELS, itemLabels } from './filings'

describe('8-K items', () => {
  it('labels items and drops the exhibits item', () => {
    expect(itemLabels(['2.02', '9.01'])).toEqual(['earnings results'])
    expect(itemLabels(['5.02'])).toEqual(['director or officer change'])
  })

  it('falls back for unknown items', () => {
    expect(itemLabels(['6.01', '1.01'])).toEqual(['item 6.01', 'material agreement'])
  })

  it('returns nothing for no items', () => {
    expect(itemLabels([])).toEqual([])
  })

  it('knows the important set', () => {
    expect([...IMPORTANT_ITEMS].sort()).toEqual(['1.03', '1.05', '2.02', '2.04', '2.06', '3.01', '4.02', '5.01', '5.02'])
    for (const item of IMPORTANT_ITEMS) expect(ITEM_LABELS[item]).toBeTruthy()
  })

  it('flags a filing with any important item', () => {
    expect(isImportant(['8.01', '2.06'])).toBe(true)
    expect(isImportant(['8.01', '9.01'])).toBe(false)
    expect(isImportant([])).toBe(false)
  })
})
