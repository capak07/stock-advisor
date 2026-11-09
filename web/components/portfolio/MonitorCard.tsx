import Link from 'next/link'
import { timeOrDate } from '@/lib/dates'
import type { FeedItem } from '@/lib/monitor'
import { safeLink, tickerHref } from '@/lib/ticker'

const KIND_LABELS: Record<FeedItem['kind'], string> = {
  news: 'News',
  filing: 'Filing',
  insider: 'Insider',
  earnings: 'Earnings',
  alert: 'Alert',
}

/** What arrived on held and watched stocks since the previous published run, newest first (Goal 1). */
export function MonitorCard({ items }: { items: FeedItem[] }) {
  return (
    <section className="card card-pad enter" aria-labelledby="monitor-h" id="monitor">
      <div className="section-head" style={{ marginBottom: 4 }}>
        <h2 id="monitor-h">What&apos;s new on your stocks</h2>
        <span className="sub">since the last run · New York time</span>
      </div>
      {items.length === 0 ? (
        <p className="sub" style={{ margin: '6px 0 0' }}>
          Nothing new since the last run.
        </p>
      ) : (
        <div className="stagger">
          {items.map((item, i) => {
            const link = item.url ? safeLink(item.url) : null
            return (
              <div key={`${item.kind}-${item.symbol}-${item.at}-${i}`} className="news-item" data-testid="monitor-item" data-kind={item.kind}>
                <span className={`badge${item.important ? ' attention' : ''}`}>{KIND_LABELS[item.kind]}</span>
                <span>
                  <Link className="text-link num" href={tickerHref(item.symbol, item.assetType ?? 'stock')}>
                    {item.symbol}
                  </Link>{' '}
                  {link ? (
                    <a href={link} target="_blank" rel="noopener noreferrer">
                      {item.title}
                    </a>
                  ) : (
                    item.title
                  )}
                  {item.important && <span className="chip review" style={{ marginLeft: 6 }}>Important</span>}
                </span>
                <span />
                <span className="sub">
                  {item.detail}
                  {item.detail && item.kind !== 'earnings' && ' · '}
                  {item.kind !== 'earnings' && timeOrDate(item.at)}
                </span>
              </div>
            )
          })}
        </div>
      )}
    </section>
  )
}
