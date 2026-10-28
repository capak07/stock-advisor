'use client'

import { useState } from 'react'
import { Tabs } from '@/components/Tabs'
import type { Market } from '@/lib/portfolio/types'

const MARKET_TABS = [
  { value: 'US', label: 'US' },
  { value: 'TSX', label: 'TSX' },
] as const

/** The page head with the US and TSX tabs; each market's panel is rendered on the server. */
export function PicksTabs({ head, panels }: { head: React.ReactNode; panels: Record<Market, React.ReactNode> }) {
  const [market, setMarket] = useState<Market>('US')
  return (
    <>
      <div className="section-head enter" style={{ marginBottom: 0 }}>
        {head}
        <Tabs items={MARKET_TABS} value={market} onChange={setMarket} label="Market" />
      </div>
      {MARKET_TABS.map(({ value }) => (
        <div key={value} className="grid gap-4" data-panel={value.toLowerCase()} role="tabpanel" aria-label={value} hidden={value !== market}>
          {panels[value]}
        </div>
      ))}
    </>
  )
}
