import { ViewTransition } from 'react'

/**
 * A 220 ms crossfade between pages (spec §5). Next 16 runs every navigation as a React transition, and a template
 * remounts on each one, so this <ViewTransition> exits with the old page and enters with the new (the `route-fade`
 * class in ledger.css). Browsers without view transitions swap at once. `default="none"`: a Refresh or a form that
 * re-renders the same page does not fade.
 */
export default function Template({ children }: { children: React.ReactNode }) {
  return (
    <ViewTransition enter="route-fade" exit="route-fade" default="none">
      {children}
    </ViewTransition>
  )
}
