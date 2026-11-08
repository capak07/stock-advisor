import type { Market } from '@/lib/portfolio/types'

const MARKETS = [
  { value: 'US', label: 'US picks', sub: 'vs SPY' },
  { value: 'TSX', label: 'TSX picks', sub: 'vs XIU.TO' },
] as const satisfies readonly { value: Market; label: string; sub: string }[]

/**
 * The page head, then both markets one after the other. Tabs hid the TSX picks behind a click the
 * owner missed (2026-11-08), so each market now has its own heading on the same page.
 */
export function PicksTabs({ head, panels }: { head: React.ReactNode; panels: Record<Market, React.ReactNode> }) {
  return (
    <>
      <div className="section-head enter" style={{ marginBottom: 0 }}>
        {head}
      </div>
      {MARKETS.map(({ value, label, sub }) => (
        <section key={value} className="grid gap-4" data-panel={value.toLowerCase()} aria-label={value}>
          <h2 className="market-head" style={{ margin: '8px 0 0' }}>
            {label} <span className="sub" style={{ fontWeight: 400 }}>{sub}</span>
          </h2>
          {panels[value]}
        </section>
      ))}
    </>
  )
}
