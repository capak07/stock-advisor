import { afterEach, describe, expect, it, vi } from 'vitest'
import { RECENT_KEY, deviceStorage, pushRecent, readRecent, writeRecent } from './recent'

const store = (value: string | null) => ({ getItem: () => value })

describe('recent searches', () => {
  it('puts the newest first, without repeats, at most 8', () => {
    expect(pushRecent(['AAPL', 'RY.TO'], 'RY.TO')).toEqual(['RY.TO', 'AAPL'])
    expect(pushRecent(['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H'], 'NVDA')).toHaveLength(8)
    expect(pushRecent(['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H'], 'NVDA')[0]).toBe('NVDA')
  })

  it('reads nothing when storage is missing, throws, or holds junk (Review Focus 4)', () => {
    expect(readRecent(null)).toEqual([])
    expect(readRecent({ getItem: () => { throw new Error('blocked') } })).toEqual([])
    expect(readRecent(store(null))).toEqual([])
    expect(readRecent(store('not json'))).toEqual([])
    expect(readRecent(store('{"a": 1}'))).toEqual([])
    expect(readRecent(store('[1, "<script>", "SHOP.TO"]'))).toEqual(['SHOP.TO'])
  })

  it('reads at most 8, from its own key', () => {
    const keys: string[] = []
    const many = JSON.stringify(['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J'])
    expect(readRecent({ getItem: (key) => (keys.push(key), many) })).toHaveLength(8)
    expect(keys).toEqual([RECENT_KEY])
    expect(RECENT_KEY).toBe('advisor.recent-symbols')
  })

  it('writes the list as JSON under its key, and never throws on write', () => {
    const written: [string, string][] = []
    writeRecent({ setItem: (key, value) => written.push([key, value]) }, ['AAPL', 'RY.TO'])
    expect(written).toEqual([[RECENT_KEY, '["AAPL","RY.TO"]']])
    expect(() => writeRecent(null, ['AAPL'])).not.toThrow()
    expect(() => writeRecent({ setItem: () => { throw new Error('quota') } }, ['AAPL'])).not.toThrow()
  })

  describe('deviceStorage', () => {
    afterEach(() => vi.unstubAllGlobals())

    it('is null on the server, and where reading localStorage throws', () => {
      expect(deviceStorage()).toBeNull()
      vi.stubGlobal('window', {
        get localStorage(): Storage {
          throw new DOMException('denied', 'SecurityError')
        },
      })
      expect(deviceStorage()).toBeNull()
    })
  })
})
