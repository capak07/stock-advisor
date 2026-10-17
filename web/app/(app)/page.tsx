import type { Metadata } from 'next'
import { ownerClient } from '@/lib/auth'

export const metadata: Metadata = { title: 'My Portfolio' }

/** My Portfolio, the home page (spec §9). Values, returns and warnings come next. */
export default async function PortfolioPage() {
  const supabase = await ownerClient()
  if (!supabase) return null // the layout is showing the not-the-owner notice
  return (
    <main className="page">
      <h1>My Portfolio</h1>
    </main>
  )
}
