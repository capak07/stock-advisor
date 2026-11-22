import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import { WatchList, type WatchRow } from './Watchlist'

// The server actions talk to Supabase; rendering the list never calls them.
vi.mock('@/app/(app)/watchlist/actions', () => ({ addWatch: vi.fn(), removeWatch: vi.fn() }))
vi.mock('@/app/(app)/search', () => ({ searchList: vi.fn() }))

const row = (over: Partial<WatchRow>): WatchRow => ({
  symbol: 'DOL.TO',
  assetType: 'stock',
  name: 'Dollarama Inc.',
  type: 'TSX',
  price: 'C$191.30',
  move: -0.3,
  verdict: 'hold',
  held: null,
  why: "doesn't qualify as a buy",
  guide: null,
  lowRank: null,
  outlook: null,
  ...over,
})

const html = (rows: WatchRow[]) => renderToStaticMarkup(<WatchList rows={rows} withVerdicts />)

describe('WatchList', () => {
  it('shows a Hold with an outlook as no clear edge, its chance, horizon and likely range', () => {
    const out = html([row({ outlook: { benchmark: 'XIU.TO', horizon: 21, pBeat: 0.54, q10: -0.064, q50: 0.006, q90: 0.071 } })])
    expect(out).toContain('No clear edge')
    expect(out).not.toContain('>Hold<')
    expect(out.replace(/<[^>]+>/g, '')).toContain('54% to beat XIU.TO over 21 trading days') // the stock page's units
    expect(out).toContain('class="range wide"')
    expect(out).toContain('likely range at 21 trading days')
    expect(out).toContain('−6.4%')
    expect(out).toContain('+7.1%')
    expect(out).toContain('C$191.30')
    expect(out).toContain('−0.3%')
  })

  it("shows a held row's Portfolio action and no chance", () => {
    const out = html([
      row({
        symbol: 'T.TO',
        held: { group: 'review', label: 'Review' },
        why: 'You hold it · Takeover bid',
        // a held row never gets an outlook from the page; even if it had one it would not show
        outlook: { benchmark: 'XIU.TO', horizon: 21, pBeat: 0.54, q10: -0.06, q50: 0.01, q90: 0.07 },
      }),
    ])
    expect(out).toContain('<span class="chip review">Review</span>')
    expect(out).toContain('You hold it · Takeover bid')
    expect(out).not.toContain('% to beat')
    expect(out).not.toContain('class="range')
  })

  it('shows its verdict without an outlook, a Hold as no clear edge (one name per verdict)', () => {
    const out = html([row({ symbol: 'SOL', assetType: 'crypto', type: 'Crypto', verdict: null, why: null })])
    expect(out).toContain('<span class="chip hold">New</span>')
    expect(out).toContain('Gets its first verdict at the next run')
    expect(out).not.toContain('% to beat')
    const hold = html([row({})])
    expect(hold).toContain('<span class="chip neutral">No clear edge</span>')
    expect(hold).not.toContain('>Hold<')
  })

  it('words a Buy and an Avoid and gives each its chance', () => {
    const buy = html([row({ verdict: 'buy', outlook: { benchmark: 'SPY', horizon: 10, pBeat: 0.64, q10: -0.03, q50: 0.02, q90: 0.06 } })])
    expect(buy).toContain('<span class="chip buy">Buy</span>')
    expect(buy.replace(/<[^>]+>/g, '')).toContain('64% to beat SPY over 10 trading days')
    const avoid = html([row({ symbol: 'DOGE', assetType: 'crypto', type: 'Crypto', verdict: 'avoid', outlook: { benchmark: 'BTC', horizon: 10, pBeat: 0.42, q10: -0.11, q50: -0.014, q90: 0.08 } })])
    expect(avoid).toContain('<span class="chip avoid">Avoid</span>')
    expect(avoid.replace(/<[^>]+>/g, '')).toContain('42% to beat BTC over 10 days') // a coin trades every day: days, not trading days
    expect(avoid).toContain('likely range at 10 days')
  })
})
