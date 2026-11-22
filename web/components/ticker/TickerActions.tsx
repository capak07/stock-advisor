'use client'

import { Activity, ChevronDown } from 'lucide-react'
import { useState } from 'react'

/**
 * The stock page's last card (ticker_2.html): Watch, Alerts and Sources side by side; Sources opens the list of
 * sources that cover the asset under them (`summary` is its one-line answer count, `children` the list).
 */
export function TickerActions({
  watch,
  alerts,
  summary,
  children,
}: {
  watch: React.ReactNode
  alerts: React.ReactNode
  summary: string
  children: React.ReactNode
}) {
  const [open, setOpen] = useState(false)
  return (
    <section className="card card-pad enter t-actions" aria-label="Watch, alerts and sources">
      <div className="ticker-actions">
        {watch}
        {alerts}
        <button type="button" className="btn btn-secondary" aria-expanded={open} aria-controls="sources" onClick={() => setOpen((o) => !o)}>
          <Activity />
          Sources
        </button>
      </div>
      <details className="src" id="sources" open={open} onToggle={(e) => setOpen(e.currentTarget.open)}>
        <summary>
          <span>{summary}</span>
          <ChevronDown aria-hidden="true" />
        </summary>
        {children}
      </details>
    </section>
  )
}
