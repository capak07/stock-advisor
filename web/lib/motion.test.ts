import { describe, expect, it } from 'vitest'
import { priceDirection, rimPoint, tickClass, tickPrices } from './motion'

/** Just enough of an element for tickPrices: its data-price, classes, a layout read and its listeners. */
function fakePrice(price?: string) {
  const classes = new Set<string>()
  const listeners = new Map<string, (event: { target: unknown; animationName: string }) => void>()
  let reflows = 0
  const el = {
    dataset: price === undefined ? {} : { price },
    classList: {
      add: (...names: string[]) => names.forEach((n) => classes.add(n)),
      remove: (...names: string[]) => names.forEach((n) => classes.delete(n)),
    },
    get offsetWidth() {
      reflows++
      return 0
    },
    addEventListener: (type: string, fn: (event: { target: unknown; animationName: string }) => void) => listeners.set(type, fn),
    removeEventListener: (type: string) => listeners.delete(type),
  }
  const end = (animationName: string, target: unknown = el) => listeners.get('animationend')?.({ target, animationName })
  return { el, classes, end, reflows: () => reflows, listening: () => listeners.has('animationend') }
}

const root = (...els: ReturnType<typeof fakePrice>[]) =>
  ({
    querySelectorAll: (selector: string) => {
      expect(selector).toBe('[data-price]')
      return els.map((e) => e.el)
    },
  }) as unknown as ParentNode

describe('tickClass', () => {
  it('flashes gain for "up", loss for "down", and nothing for anything else', () => {
    expect(tickClass('up')).toBe('tick-up')
    expect(tickClass('down')).toBe('tick-down')
    expect(tickClass(undefined)).toBeNull()
    expect(tickClass('flat')).toBeNull()
  })
})

describe('priceDirection', () => {
  it('marks a price that fell down, one that rose or held up, and leaves an unknown move unmarked', () => {
    expect(priceDirection(-0.4)).toBe('down')
    expect(priceDirection(1.2)).toBe('up')
    expect(priceDirection(0)).toBe('up')
    expect(priceDirection(null)).toBeUndefined()
    expect(priceDirection(undefined)).toBeUndefined()
    expect(priceDirection(Number.NaN)).toBeUndefined()
  })
})

describe('tickPrices', () => {
  it('adds tick-up or tick-down once to each priced element and counts them', () => {
    const up = fakePrice('up')
    const down = fakePrice('down')
    const odd = fakePrice('sideways')
    expect(tickPrices(root(up, down, odd))).toBe(2)
    expect([...up.classes]).toEqual(['tick-up'])
    expect([...down.classes]).toEqual(['tick-down'])
    expect(odd.classes.size).toBe(0)
  })

  it('restarts a flash still running from the last Refresh, and a price that turned keeps only the new direction', () => {
    const p = fakePrice('down')
    p.classes.add('tick-up')
    tickPrices(root(p))
    expect(p.reflows()).toBe(1) // the removal is laid out first, so the animation starts again
    expect([...p.classes]).toEqual(['tick-down'])
  })

  it('takes the class off when its own flash ends, not when a child animation ends', () => {
    const p = fakePrice('up')
    tickPrices(root(p))
    p.end('tick', {}) // a descendant's animation bubbling up
    p.end('fade') // another animation on the element
    expect([...p.classes]).toEqual(['tick-up'])
    p.end('tick')
    expect(p.classes.size).toBe(0)
    expect(p.listening()).toBe(false)
  })
})

describe('rimPoint', () => {
  it('is the pointer position inside the card, in px', () => {
    expect(rimPoint({ clientX: 130, clientY: 45 }, { left: 100, top: 20 })).toEqual({ mx: '30px', my: '25px' })
  })
})
