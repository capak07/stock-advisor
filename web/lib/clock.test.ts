import { describe, expect, it } from 'vitest'
import { clockNow } from './clock'

const real = new Date('2026-11-25T23:15:00Z') // 6:15 PM in New York
const pinned = '2026-11-25T17:00:00.000Z' // noon in New York

describe('clockNow', () => {
  it('is the real time unless the browser tests turned pinning on', () => {
    expect(clockNow(real, pinned, false)).toBe('2026-11-25T23:15:00.000Z')
    expect(clockNow(real, undefined, false)).toBe('2026-11-25T23:15:00.000Z')
  })

  it('is the pinned time when pinning is on and the cookie holds one', () => {
    expect(clockNow(real, pinned, true)).toBe(pinned)
  })

  it('falls back to the real time with no cookie or one that is not a time', () => {
    expect(clockNow(real, undefined, true)).toBe('2026-11-25T23:15:00.000Z')
    expect(clockNow(real, 'not a time', true)).toBe('2026-11-25T23:15:00.000Z')
    expect(clockNow(real, '', true)).toBe('2026-11-25T23:15:00.000Z')
  })
})
