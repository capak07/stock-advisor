import { ViewTransition } from 'react'

/**
 * The same 220 ms crossfade as app/(app)/template.tsx, for one stock page to another. The (app) template is keyed
 * by its child segment (`ticker`), which /ticker/A → /ticker/B keeps, so it does not remount; this one sits under
 * the `[symbol]` segment, whose key changes with the symbol, so the old stock page exits and the new one enters.
 * Coming to a stock page from another route, the (app) template's boundary is the one that enters: React animates
 * only the outermost <ViewTransition> of a tree that mounts, so this one does not fade a second time.
 */
export default function TickerTemplate({ children }: { children: React.ReactNode }) {
  return (
    <ViewTransition enter="route-fade" exit="route-fade" default="none">
      {children}
    </ViewTransition>
  )
}
