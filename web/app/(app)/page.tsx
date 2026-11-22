import type { Metadata } from 'next'
import { MonitorCard } from '@/components/portfolio/MonitorCard'
import { ownerClient } from '@/lib/auth'
import { loadMonitorFeed } from '@/lib/data/monitor'

export const metadata: Metadata = { title: 'Today' }

const DAY = new Intl.DateTimeFormat('en-CA', { weekday: 'long', month: 'short', day: 'numeric', timeZone: 'America/Toronto' })

/** Today, the home page (spec §7.1): what changed on the owner's stocks so far; the summary cards join it later. */
export default async function TodayPage() {
  const supabase = await ownerClient()
  if (!supabase) return null // the layout is showing the not-the-owner notice
  return (
    <main className="page">
      <div className="page-head enter">
        <div>
          <div className="label">{DAY.format(new Date())}</div>
          <h1 style={{ marginTop: 6 }}>Today</h1>
        </div>
      </div>
      <MonitorCard items={await loadMonitorFeed(supabase)} />
    </main>
  )
}
