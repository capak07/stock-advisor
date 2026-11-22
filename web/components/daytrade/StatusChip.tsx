'use client'

import { useState } from 'react'
import type { ChipTone } from '@/lib/daytrade'

/**
 * A signal's status chip (`statusChip`). Keyed by its label, it remounts and plays `flip` when the
 * status changes between renders (the page refreshes itself while the day is live); the first render
 * does not flip.
 */
export function StatusChip({ label, tone }: { label: string; tone: ChipTone }) {
  const [shown, setShown] = useState(label)
  const [changed, setChanged] = useState(false)
  if (shown !== label) {
    // React's pattern for state that follows a prop: set during render, no effect
    setShown(label)
    setChanged(true)
  }
  return (
    <span key={label} className={`chip ${tone}${changed ? ' flip' : ''}`}>
      {label}
    </span>
  )
}
