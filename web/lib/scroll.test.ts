import { describe, expect, it } from 'vitest'
import { nextHidden } from './scroll'

describe('nextHidden', () => {
  it('hides only when scrolling down past 120 px', () => {
    expect(nextHidden(100, 110, false)).toBe(false) // still near the top
    expect(nextHidden(200, 260, false)).toBe(true)
    expect(nextHidden(260, 200, true)).toBe(false) // scrolling up shows it
  })
  it('ignores moves under 6 px', () => {
    expect(nextHidden(300, 304, false)).toBe(false)
    expect(nextHidden(300, 296, true)).toBe(true)
  })
})
