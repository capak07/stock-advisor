'use client'

import { useEffect, useState } from 'react'
import { SCROLL_JITTER_PX, nextHidden } from '@/lib/scroll'

/**
 * True while the phone tab bar should be out of the way: the page is scrolling down past the top (lib/scroll.ts).
 * One passive scroll listener, read at most once a frame.
 */
export function useHideOnScroll(): boolean {
  const [hidden, setHidden] = useState(false)

  useEffect(() => {
    let last = window.scrollY
    let frame = 0
    const read = () => {
      frame = 0
      const y = window.scrollY
      const prev = last
      if (Math.abs(y - prev) < SCROLL_JITTER_PX) return // jitter: measure the next move from the same place
      last = y
      setHidden((h) => nextHidden(prev, y, h))
    }
    const onScroll = () => {
      if (!frame) frame = requestAnimationFrame(read)
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => {
      window.removeEventListener('scroll', onScroll)
      if (frame) cancelAnimationFrame(frame)
    }
  }, [])

  return hidden
}
