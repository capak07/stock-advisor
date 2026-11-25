import { ChevronDown } from 'lucide-react'
import type { ReactNode } from 'react'

/**
 * A card's supporting lines, folded under one "Details" line and closed until tapped (owner request
 * 2026-11-25: a card leads with its answer). Native <details>: no script, and the text stays in the page.
 * `bare` drops the rule above it, for a fold inside a table cell.
 */
export function More({
  label = 'Details',
  bare = false,
  testId,
  children,
}: {
  label?: string
  bare?: boolean
  testId?: string
  children: ReactNode
}) {
  return (
    <details className={bare ? 'more bare' : 'more'} data-testid={testId}>
      <summary>
        <span>{label}</span>
        <ChevronDown className="chev" aria-hidden />
      </summary>
      <div className="more-body">{children}</div>
    </details>
  )
}
