'use client'

import { useState } from 'react'
import { Tabs } from '@/components/Tabs'
import type { Market } from '@/lib/portfolio/types'

const BENCHMARK: Record<Market, string> = { US: 'SPY', TSX: 'XIU.TO' }
const MARKETS: readonly Market[] = ['US', 'TSX']

/**
 * The US | TSX segmented control over each market's panel (spec §7.4). Each tab carries its pick
 * count, so a market's picks are never hidden behind a tab without saying so (the owner missed the
 * TSX picks behind a bare tab, 2026-11-08); it opens on the first market that has picks. Both
 * panels are rendered, the other one hidden.
 */
export function PicksTabs({ counts, panels }: { counts: Record<Market, number>; panels: Record<Market, React.ReactNode> }) {
  const [market, setMarket] = useState<Market>(() => MARKETS.find((m) => counts[m] > 0) ?? 'US')
  const n = counts[market]
  return (
    <>
      <div className="picks-tabs enter">
        <Tabs
          className="seg"
          label="Market"
          items={MARKETS.map((m) => ({ value: m, label: `${m} · ${counts[m]}` }))}
          value={market}
          onChange={setMarket}
        />
        <span className="sub">
          {n === 0 ? 'No picks' : `${n} ${n === 1 ? 'pick' : 'picks'}`} vs {BENCHMARK[market]}
        </span>
      </div>
      {MARKETS.map((m) => (
        <section key={m} role="tabpanel" aria-label={m} data-panel={m.toLowerCase()} hidden={m !== market}>
          {panels[m]}
        </section>
      ))}
    </>
  )
}
