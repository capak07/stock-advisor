'use client'

import { useEffect } from 'react'
import { rimPoint } from '@/lib/motion'

/**
 * The highlight that follows the pointer along a `.card.rim` edge (ledger.css): one delegated pointermove sets
 * --mx / --my on the card under the pointer. Desktop pointers only; rendered once by Shell.
 */
export function RimLight() {
  useEffect(() => {
    if (!matchMedia('(hover: hover) and (pointer: fine)').matches) return
    const move = (event: PointerEvent) => {
      if (event.pointerType === 'touch') return
      const card = event.target instanceof Element ? event.target.closest<HTMLElement>('.card.rim') : null
      if (!card) return
      const { mx, my } = rimPoint(event, card.getBoundingClientRect())
      card.style.setProperty('--mx', mx)
      card.style.setProperty('--my', my)
    }
    document.addEventListener('pointermove', move, { passive: true })
    return () => document.removeEventListener('pointermove', move)
  }, [])
  return null
}
