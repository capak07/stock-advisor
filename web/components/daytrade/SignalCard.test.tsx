import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { SignalCard } from './SignalCard'
import type { Signal } from '@/lib/daytrade'

// Tuesday, Nov 10 2026 (EST, UTC−5)
const at = (hhmm: string) => new Date(`2026-11-10T${hhmm}:00-05:00`).toISOString()

const signal = (over: Partial<Signal> = {}): Signal => ({
  id: 1,
  day: '2026-11-10',
  symbol: 'TGTX',
  market: 'US',
  name: 'TG Therapeutics',
  triggerAt: at('10:10'),
  entry: 67.65,
  orHigh: 67.5,
  orLow: 64.6,
  stop: 66.05,
  target: 70.85,
  flatBy: at('15:55'),
  volumeX: 2.1,
  costPct: 3.1,
  costR: 1.31,
  replay: { replays: 10000, target_first: 0.341, stop_first: 0.52, neither: 0.139, green: 0.48, avg_r: 0.4, sessions: 55 },
  history: { sessions: 55, fired: 37, target: 5, stop: 20, neither: 12, avg_r: -0.12 },
  netReplayR: 0.2,
  netHistoryR: 0.3,
  eligible: true,
  rank: 1,
  bestRank: 1,
  skillRank: 2,
  headlines: [{ title: 'TG Therapeutics beats estimates', url: 'https://finance.yahoo.com/tgtx', published_at: at('09:40'), outlet: 'Reuters' }],
  status: 'open',
  lastPrice: null,
  lastAt: null,
  exitAt: null,
  exitPrice: null,
  grossR: null,
  netR: null,
  ...over,
})

const VERDICT = '10,000 replays: target first 34% · stop first 52% · neither 14% · green at close 48%'
const render = (s: Signal, props: { list?: 'skill' | 'costs'; fresh?: boolean } = {}) =>
  renderToStaticMarkup(<SignalCard signal={s} fresh={props.fresh ?? true} maxLossCad={50} usdCad={1.4} list={props.list} />)
/** The text of the markup, tags dropped. */
const text = (html: string) => html.replace(/<[^>]+>/g, '')

describe('SignalCard', () => {
  it('leads with the answer, the tiles and the shares; the rest waits under Details', () => {
    const html = render(signal({ status: 'flat', exitAt: at('15:55'), exitPrice: 68.12, grossR: 0.29, netR: -1.02 }))
    const [shown, folded = ''] = html.split('<details')
    expect(shown).toContain('<b class="answer-big num loss">−1.02R after costs</b><span class="answer-note">Sold US$68.12 at 3:55 PM</span>')
    expect(text(shown)).toContain('Entry US$67.6510:10 AM') // the trigger time under the entry
    expect(text(shown)).toContain('Target US$70.85+4.7%')
    expect(text(shown)).toContain('≈ 22 shares (risking ≈ C$49 at the stop)')
    for (const line of [VERDICT, 'Cost1.31R', 'Opening range US$64.60–US$67.50', 'last 55 sessions: fired 37 times', 'volume 2.1×', 'TG Therapeutics beats estimates']) {
      expect(text(shown)).not.toContain(line)
      expect(text(folded)).toContain(line)
    }
    expect(text(folded)).toContain('Flat at close 3:55 PM (US$68.12) · +0.29R before costs, −1.02R after')
  })

  it('the full card: entry, target and stop tiles, the cost in R, the net R values and the verdict line', () => {
    const html = render(signal())
    // the currency in the label, the figure whole: "Entry US$" over "67.65"
    expect(html).toMatch(/>Entry US\$</)
    expect(html).toMatch(/>Target US\$</)
    expect(html).toMatch(/>Stop US\$</)
    expect(html).toContain('<b>67.65</b>')
    const t = text(html)
    expect(t).toContain('Entry US$67.65')
    expect(t).toContain('Target US$70.85')
    expect(t).toContain('Stop US$66.05')
    // how far each level is from the entry, under its figure
    expect(t).toContain('Target US$70.85+4.7%')
    expect(t).toContain('Stop US$66.05−2.4%')
    expect(t).toContain('Cost1.31R')
    expect(t).toContain('History, net+0.30R')
    expect(t).toContain('Replays, net+0.20R')
    expect(t).toContain(VERDICT)
    expect(t).toContain('Opening range US$64.60–US$67.50 · flat by 3:55 PM')
    expect(t).toContain('≈ 22 shares (risking ≈ C$49 at the stop)')
    expect(t).toContain('TG Therapeutics beats estimates')
    expect(t).toContain('Fresh')
  })

  it("a skill card is the same full card, its strength under Details", () => {
    const html = render(signal({ status: 'target', exitAt: at('10:50'), exitPrice: 70.85, grossR: 2, netR: 0.64 }), { list: 'skill' })
    const [shown, folded = ''] = html.split('<details')
    expect(shown).toContain('<b class="answer-big num gain">+0.64R after costs</b><span class="answer-note">Sold US$70.85 at 10:50 AM</span>')
    expect(shown).toContain('<span class="rank">2</span>') // its place in the skill's list
    expect(shown.match(/class="stat"/g)).toHaveLength(3)
    expect(text(shown)).toContain('≈ 22 shares (risking ≈ C$49 at the stop)')
    expect(text(folded)).toContain('+0.22% above the range high')
    expect(text(render(signal()))).not.toContain('above the range high') // only a skill card has the strength
  })

  it('a late open signal says so with the last price, and its chip reads Late', () => {
    const t = text(render(signal({ lastPrice: 68.4, lastAt: at('10:40') }), { fresh: false }))
    expect(t).toContain('Late: the price has moved since the signal')
    expect(t).toContain('Last price US$68.40 at 10:40 AM')
    expect(t).not.toContain('Fresh')
  })
})
