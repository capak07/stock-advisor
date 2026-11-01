'use client'

import { useState } from 'react'

export interface HeadlineView {
  id: number
  title: string
  /** Null when the stored link isn't a web page. */
  link: string | null
  outlet: string
  when: string
  score: string
  tone: 'pos' | 'neg' | 'neu'
}

export interface NewsKpi {
  label: string
  value: string
  tone: 'gain' | 'loss' | ''
}

const SHOWN = 12

/** The last 48 hours of headlines with FinBERT scores, and the run's news numbers (ticker_1.html). */
export function NewsCard({ headlines, kpis, source }: { headlines: HeadlineView[]; kpis: NewsKpi[] | null; source: string | null }) {
  const [all, setAll] = useState(false)
  const shown = all ? headlines : headlines.slice(0, SHOWN)
  return (
    <section className="card card-pad enter" aria-labelledby="news-h">
      <div className="section-head" style={{ marginBottom: 4 }}>
        <h2 id="news-h">News</h2>
        <span className="sub">48 hours</span>
      </div>
      {kpis && (
        <div className="kpis" style={{ margin: '6px 0 4px' }}>
          {kpis.map((k) => (
            <div key={k.label} className="kpi">
              <span className="label">{k.label}</span>
              <b className={k.tone}>{k.value}</b>
            </div>
          ))}
        </div>
      )}
      {headlines.length === 0 ? (
        <p className="sub" style={{ margin: '6px 0 0' }}>
          {source ? `No headlines in the 48 hours before the ${source} run.` : 'No headlines in the last 48 hours.'}
        </p>
      ) : (
        <div className="stagger" id="headlines">
          {shown.map((h) => (
            <div key={h.id} className="news-item">
              <span className={`sent ${h.tone}`}>{h.score}</span>
              {h.link ? (
                <a href={h.link} target="_blank" rel="noopener noreferrer">
                  {h.title}
                </a>
              ) : (
                <span>{h.title}</span>
              )}
              <span />
              <span className="sub">
                {h.outlet} · {h.when}
              </span>
            </div>
          ))}
        </div>
      )}
      {headlines.length > SHOWN && (
        <button type="button" className="btn btn-ghost btn-sm" style={{ marginTop: 8, width: '100%' }} onClick={() => setAll((a) => !a)}>
          {all ? 'Show fewer' : `Show all ${headlines.length} headlines`}
        </button>
      )}
      <p className="sub" style={{ margin: '8px 0 0' }}>
        Headlines link to the publisher. Google News links open Google&apos;s redirect page. Sentiment is FinBERT, from
        −1 to +1.{source && ` The headlines and counts cover the 48 hours before the ${source} run.`}
      </p>
    </section>
  )
}
