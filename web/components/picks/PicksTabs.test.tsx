import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { PicksTabs } from './PicksTabs'

const panels = { US: <p>us-panel</p>, TSX: <p>tsx-panel</p> }
/** The <section> of one market's panel, as rendered. */
const panel = (html: string, market: string) => html.match(new RegExp(`<section[^>]*data-panel="${market}"[^>]*>`))![0]
const tab = (html: string, label: string) => html.match(new RegExp(`<button[^>]*>${label}</button>`))![0]

describe('PicksTabs', () => {
  it('opens on the first market with picks: TSX when US has none', () => {
    const html = renderToStaticMarkup(<PicksTabs counts={{ US: 0, TSX: 2 }} panels={panels} />)
    expect(tab(html, 'TSX · 2')).toContain('aria-selected="true"')
    expect(tab(html, 'US · 0')).toContain('aria-selected="false"')
    expect(panel(html, 'tsx')).not.toContain('hidden')
    expect(panel(html, 'us')).toContain('hidden')
    expect(html).toContain('2 picks vs XIU.TO')
  })

  it('opens on US when it has picks, and on US when neither has', () => {
    const both = renderToStaticMarkup(<PicksTabs counts={{ US: 1, TSX: 3 }} panels={panels} />)
    expect(tab(both, 'US · 1')).toContain('aria-selected="true"')
    expect(panel(both, 'us')).not.toContain('hidden')
    expect(panel(both, 'tsx')).toContain('hidden')
    expect(both).toContain('1 pick vs SPY')

    const none = renderToStaticMarkup(<PicksTabs counts={{ US: 0, TSX: 0 }} panels={panels} />)
    expect(tab(none, 'US · 0')).toContain('aria-selected="true"')
    expect(none).toContain('No picks vs SPY')
  })
})
