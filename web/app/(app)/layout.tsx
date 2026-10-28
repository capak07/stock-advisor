import { LogOut } from 'lucide-react'
import { Shell } from '@/components/shell/Shell'
import { session } from '@/lib/auth'
import { liveQuotes } from '@/lib/data/quotes'
import { lastPublishedRun, recentRuns } from '@/lib/data/runs'
import { signOut } from './actions'

/**
 * Every signed-in page. Only the owner named in `app_config` sees data (row-level security, spec
 * §8); anyone else who signs in gets this notice instead of empty pages.
 */
export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const { supabase, owner } = await session()
  if (!owner) {
    return (
      <main className="login-wrap">
        <div className="login">
          <div className="card empty" style={{ padding: 24 }}>
            <strong>This account isn&apos;t the owner</strong>
            <span>
              The dashboard shows data only to the owner set in <code>app_config</code>. Sign out and sign in as the
              owner.
            </span>
            <form action={signOut}>
              <button type="submit" className="btn btn-secondary">
                <LogOut />
                Sign out
              </button>
            </form>
          </div>
        </div>
      </main>
    )
  }

  const [runs, lastPublished, live] = await Promise.all([recentRuns(supabase), lastPublishedRun(supabase), liveQuotes()])
  return (
    <Shell runs={runs} lastPublished={lastPublished} liveAt={live?.fetchedAt ?? null}>
      {children}
    </Shell>
  )
}
