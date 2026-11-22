'use client'

import { useLayoutEffect, useRef } from 'react'

type Place = (pill: HTMLElement, link: HTMLElement) => void

// The sidebar pill moves down the list; the transition (300 ms, a small overshoot) is on .nav-pill in ledger.css.
const placeY: Place = (pill, link) => {
  pill.style.transform = `translateY(${link.offsetTop}px)`
}
// The tab pill sits 6 px in from the bar's edge (.tab-pill's left), so it moves by the tab's offset less that.
const placeX: Place = (pill, link) => {
  pill.style.width = `${link.offsetWidth}px`
  pill.style.transform = `translateX(${link.offsetLeft - 6}px)`
}

/**
 * Keeps a pill under the link to `target` among the pill's siblings, or hides it when `target` is null. It slides
 * (transform only) when the target changes, but is put in place without sliding when it first appears, so it does
 * not sweep in from the top on load. With `stretch`, each slide also squashes it mid-way (.tab-pill.stretch).
 */
function useSlidingPill(target: string | null, place: Place, stretch: boolean) {
  const ref = useRef<HTMLSpanElement>(null)
  const placed = useRef<string | null>(null)

  useLayoutEffect(() => {
    const pill = ref.current
    if (!pill) return
    const find = () => (target === null ? null : pill.parentElement?.querySelector<HTMLElement>(`a[href="${target}"]`) ?? null)
    const link = find()
    if (!link) {
      pill.style.opacity = '0'
      placed.current = null
      return
    }
    if (placed.current === null) {
      pill.style.transition = 'none'
      place(pill, link)
      void pill.offsetWidth // apply the position before the transition comes back
      pill.style.transition = ''
    } else if (placed.current !== target) {
      place(pill, link)
      if (stretch) {
        pill.classList.remove('stretch')
        void pill.offsetWidth // restart the animation
        pill.classList.add('stretch')
      }
    }
    pill.style.opacity = '1'
    placed.current = target
    const onResize = () => {
      const now = find()
      if (now) place(pill, now)
    }
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [target, place, stretch])

  return ref
}

/** The desktop sidebar's "you are here" pill (spec §5): slides to the current link. */
export function NavPill({ target }: { target: string | null }) {
  const ref = useSlidingPill(target, placeY, false)
  return <span ref={ref} className="nav-pill" aria-hidden="true" style={{ opacity: 0 }} />
}

/** The phone tab bar's liquid pill: slides to the tapped tab and stretches mid-way; hidden on pages under More. */
export function TabPill({ target }: { target: string | null }) {
  const ref = useSlidingPill(target, placeX, true)
  return <span ref={ref} className="tab-pill" aria-hidden="true" style={{ opacity: 0 }} />
}
