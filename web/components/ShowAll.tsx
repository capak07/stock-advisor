'use client'

import { ChevronDown } from 'lucide-react'
import { Children, useState, type ReactNode } from 'react'

/**
 * A list that shows its first `limit` children and a "Show all" button that expands it in place
 * (and folds it back). Without a limit, or with no more children than it, the whole list and no button.
 */
export function ShowAll({ limit, className, children }: { limit?: number; className?: string; children: ReactNode }) {
  const [open, setOpen] = useState(false)
  const items = Children.toArray(children)
  const folds = limit !== undefined && items.length > limit
  return (
    <>
      <div className={className}>{folds && !open ? items.slice(0, limit) : items}</div>
      {folds && (
        <button type="button" className="btn btn-ghost btn-sm show-all" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
          {open ? 'Show fewer' : `Show all ${items.length}`}
          <ChevronDown aria-hidden />
        </button>
      )}
    </>
  )
}
