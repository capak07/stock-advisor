import { LogOut, TriangleAlert } from 'lucide-react'
import Link from 'next/link'
import { signOut } from '@/app/(app)/actions'
import { CREDITS, DISCLAIMER } from '@/lib/copy'
import type { Run } from '@/lib/runs'
import { STATUS_DOT, runLabel, runSources, runWhen, staleNotice } from '@/lib/runs'
import { ThemeToggle } from '../ThemeToggle'
import { ToastProvider } from '../Toast'
import { BottomTabs, SidebarLinks } from './Navigation'
import { RunsPill, type RunView } from './RunsPill'

const brand = (
  <span className="brand-mark" aria-hidden="true">
    A
  </span>
)

/**
 * The app frame from the mockups: a sidebar on desktop, a status bar with the latest runs, the
 * stale banner, the disclaimer, and tabs at the bottom on phones.
 */
export function Shell({
  runs,
  lastPublished,
  children,
}: {
  runs: Run[]
  lastPublished: Run | null
  children: React.ReactNode
}) {
  const views: RunView[] = runs.map((r) => ({
    id: r.id,
    dot: STATUS_DOT[r.status],
    label: runLabel(r),
    when: runWhen(r),
    status: r.status,
    note: r.status === 'failed' ? (r.summary.failed_reason ?? []).join('; ') || null : null,
    sources: runSources(r),
  }))
  const latest = runs[0]
  const sources = latest ? runSources(latest) : null
  const stale = staleNotice(runs, lastPublished)
  return (
    <ToastProvider>
      <div className="shell">
        <aside className="sidebar" aria-label="Main">
          <Link className="brand" href="/">
            {brand}ADVISOR
          </Link>
          <SidebarLinks />
          <div className="sidebar-foot">
            <form action={signOut}>
              <button type="submit" className="btn btn-ghost btn-sm" style={{ paddingLeft: 0 }}>
                <LogOut />
                Sign out
              </button>
            </form>
          </div>
        </aside>
        <div className="content">
          <header className="statusbar">
            <Link className="brand" href="/" aria-label="Advisor">
              {brand}
            </Link>
            <RunsPill runs={views} />
            {sources && (
              <span className="pill hide-sm">
                <span className="num">{sources}</span>&nbsp;sources
              </span>
            )}
            {/* Every market is in its paper period until picks are graded live (spec §6.6, Plan 4). */}
            <span className="pill hide-sm" title="No picks graded live yet">
              <span className="dot paper" />
              US Paper
            </span>
            <span className="pill hide-sm" title="No picks graded live yet">
              <span className="dot paper" />
              TSX Paper
            </span>
            <span className="status-spacer" />
            <ThemeToggle />
          </header>
          <div className="banners" aria-live="polite">
            {stale && (
              <div className="banner danger">
                <TriangleAlert />
                <div>
                  <strong>{stale.title}</strong> {stale.detail}
                </div>
              </div>
            )}
          </div>
          {children}
          <footer className="disclaimer">
            {DISCLAIMER}
            <br />
            {CREDITS}
          </footer>
        </div>
        <BottomTabs />
      </div>
    </ToastProvider>
  )
}
