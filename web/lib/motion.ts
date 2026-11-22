/** Small DOM behaviours behind the motion rules in ledger.css (spec §5): price ticks and the rim light. */

export type TickClass = 'tick-up' | 'tick-down'

/** The flash for an element's `data-price`: gain-soft when it went up, loss-soft when it went down. */
export function tickClass(direction: string | undefined): TickClass | null {
  return direction === 'up' ? 'tick-up' : direction === 'down' ? 'tick-down' : null
}

/**
 * Flashes every `[data-price="up" | "down"]` element under `root` once (the `tick` keyframes on its ::after).
 * A flash still running from an earlier Refresh restarts; the class comes off when the element's own flash ends.
 * Returns how many elements flash.
 */
export function tickPrices(root: ParentNode): number {
  let count = 0
  for (const el of Array.from(root.querySelectorAll<HTMLElement>('[data-price]'))) {
    const cls = tickClass(el.dataset.price)
    if (!cls) continue
    el.classList.remove('tick-up', 'tick-down')
    void el.offsetWidth // lay out the removal, so adding the class starts the animation again
    el.classList.add(cls)
    const done = (event: AnimationEvent) => {
      // animationend bubbles: only the element's own flash takes the class off
      if (event.target !== el || event.animationName !== 'tick') return
      el.classList.remove(cls)
      el.removeEventListener('animationend', done)
    }
    el.addEventListener('animationend', done)
    count++
  }
  return count
}

/** Where the pointer is inside a card, as the --mx / --my the rim light's gradient is centred on. */
export function rimPoint(pointer: { clientX: number; clientY: number }, rect: { left: number; top: number }) {
  return { mx: `${pointer.clientX - rect.left}px`, my: `${pointer.clientY - rect.top}px` }
}
