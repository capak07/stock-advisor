import { Info, TriangleAlert } from 'lucide-react'
import type { Metadata } from 'next'
import Link from 'next/link'
import type { CSSProperties } from 'react'
import { OrderDisclaimer, OrderGuide } from '@/components/OrderGuide'
import { SplitForm } from '@/components/invest/SplitForm'
import { ownerClient } from '@/lib/auth'
import { loadInvestData } from '@/lib/data/invest'
import { loadFx } from '@/lib/data/portfolio'
import { addDays, shortDay } from '@/lib/dates'
import { fmtMoney, fmtPct, fmtQty } from '@/lib/format'
import { investGuide, type OrderContext } from '@/lib/guidance'
import { allocate, type Hold, type StockLine } from '@/lib/invest/allocate'
import { addWeekdays, parseInvestInputs, type AssetChoice } from '@/lib/invest/inputs'
import type { OrderPlan, StopRules } from '@/lib/orders'
import type { Market } from '@/lib/portfolio/types'
import { KIND_LABEL, type Run } from '@/lib/runs'
import { tickerHref } from '@/lib/ticker'

export const metadata: Metadata = { title: 'Invest' }

interface Props {
  searchParams: Promise<{ amount?: string | string[]; asset?: string | string[]; stocks?: string | string[]; hold?: string | string[] }>
}

const warning = (names: string, mixed: boolean) =>
  mixed
    ? `Not validated: only the ${names} marked “passes the bar” meet the picks' bar today. The rest are the model's best-ranked, not recommendations.`
    : "Not validated: none of these meets the picks' bar today. They're the model's best-ranked, not recommendations."

/**
 * Invest: split an amount over up to five of the newest run's best-ranked stocks, or its best-ranked
 * coins. Returns are always excess over the benchmark. A run scores a coin only when it is held or watched.
 */
export default async function InvestPage({ searchParams }: Props) {
  const supabase = await ownerClient()
  if (!supabase) return null // the layout is showing the not-the-owner notice
  const inputs = parseInvestInputs(await searchParams)
  const [data, fx] = await Promise.all([loadInvestData(supabase), loadFx(supabase)])
  const orders = { now: new Date(), usdCad: fx.latest()?.usdCad ?? null }
  const ready = data !== null && inputs.amount !== null && inputs.asset !== null && inputs.stocks !== null && inputs.hold !== null

  return (
    <main className="page">
      <div className="enter">
        <h1>Invest</h1>
        <p className="sub">Type an amount and choose stocks or crypto. It is split over the model&apos;s best-ranked names.</p>
      </div>
      <section className="card card-pad enter" aria-labelledby="split-h">
        <h2 id="split-h" style={{ marginBottom: 12 }}>
          Split an amount
        </h2>
        <SplitForm inputs={inputs} />
      </section>
      {data === null ? (
        <section className="card card-pad enter">
          <div className="banner info">
            <Info />
            <div>No forecasts yet. They appear after the next run.</div>
          </div>
        </section>
      ) : (
        ready && (
          <Result
            run={data.run}
            amount={inputs.amount!}
            asset={inputs.asset!}
            hold={inputs.hold!}
            scored={inputs.asset === 'crypto' ? data.coins.length : data.stocks.length}
            noTsx126={!data.stocks.some((c) => c.market === 'TSX' && c.rows.some((r) => r.horizonDays === 126))}
            orders={orders}
            stopRules={data.stopRules}
            allocation={allocate({
              amount: inputs.amount!,
              stocks: inputs.stocks!,
              horizons: inputs.horizons,
              usdFxFeePct: data.usdFxFeePct,
              cryptoFeePct: data.cryptoFeePct,
              candidates: inputs.asset === 'crypto' ? data.coins : data.stocks,
              held: inputs.asset === 'crypto' ? data.heldCoins : data.heldStocks,
            })}
          />
        )
      )}
    </main>
  )
}

function Result({
  run,
  amount,
  asset,
  hold,
  scored,
  noTsx126,
  orders,
  stopRules,
  allocation,
}: {
  run: Run
  amount: number
  asset: AssetChoice
  hold: Hold
  /** How many names this run forecast for the chosen kind, before held names are left out. */
  scored: number
  noTsx126: boolean
  orders: OrderContext
  stopRules: Partial<Record<Market, StopRules>>
  allocation: ReturnType<typeof allocate>
}) {
  const { stocks, uninvested, notValidated, evenSplit } = allocation
  const noun = asset === 'crypto' ? 'coin' : 'stock'
  const names = asset === 'crypto' ? 'coins' : 'stocks'
  const mixed = notValidated && stocks.some((s) => s.qualifies)
  const guides = new Map(stocks.map((s) => [s.symbol, investGuide(s, orders, stopRules)]))
  return (
    <section className="card card-pad enter" aria-labelledby="result-h">
      <div className="section-head" style={{ marginBottom: 6 }}>
        <h2 id="result-h">Where {fmtMoney(amount)} would go</h2>
      </div>
      <p className="sub" style={{ margin: '0 0 12px' }}>
        From the {KIND_LABEL[run.kind]} run of {shortDay(run.et_date)} ·{' '}
        {asset === 'crypto'
          ? 'returns are vs BTC (Bitcoin itself vs SPY), not plain gains'
          : 'returns are vs SPY (US) or XIU.TO (TSX), not plain gains'}
      </p>
      {notValidated && (
        <div className="banner warn" role="alert" style={{ marginBottom: 12 }}>
          <TriangleAlert />
          <div>{warning(names, mixed)}</div>
        </div>
      )}
      <ul className="invest-list stagger" id="invest-lines">
        {stocks.map((line, i) => (
          <Line key={line.symbol} line={line} run={run} mixed={mixed} index={i} guide={guides.get(line.symbol) ?? null} />
        ))}
      </ul>
      {stocks.length === 1 && (
        <p className="sub" style={{ margin: '10px 0 0' }} id="invest-concentrated">
          All in one {noun}: no spread of risk.
        </p>
      )}
      {evenSplit && (
        <p className="sub" style={{ margin: '10px 0 0' }}>
          With two {names} the 40% cap can&apos;t hold, so the money is split evenly.
        </p>
      )}
      {asset === 'stocks' && hold === '126' && noTsx126 && (
        <p className="sub" style={{ margin: '10px 0 0' }}>
          No TSX stock has a 6-month forecast this run, so only US stocks are ranked.
        </p>
      )}
      {asset === 'stocks' && (hold === 'any' || hold === '21') && (
        <p className="sub" style={{ margin: '10px 0 0' }}>
          Frequent short-term trades in a TFSA can be treated as a business, which makes the gains taxable; a longer hold
          avoids that (not tax advice).
        </p>
      )}
      {uninvested > 0 && asset === 'crypto' && scored === 0 && (
        <p className="i-uninvested" id="invest-uninvested">
          No coin was scored this run. A run scores a coin when you hold or watch it, and the whole{' '}
          <b className="num">{fmtMoney(amount)}</b> stays uninvested.
        </p>
      )}
      {uninvested > 0 && !(asset === 'crypto' && scored === 0) && (
        <p className="i-uninvested" id="invest-uninvested">
          <b className="num">{fmtMoney(uninvested)}</b> not invested: no {noun} is expected to beat its benchmark today.
        </p>
      )}
      <div className="invest-foot">
        <b className="num">Total {fmtMoney(amount)}</b>
        <span className="sub">Not financial or tax advice. Forecasts are probabilistic and can be wrong.</span>
      </div>
      {stocks.some((s) => s.assetType === 'stock' && s.shares !== null) && (
        <p className="sub" style={{ margin: '8px 0 0' }}>
          Shares are approximate; Wealthsimple allows fractional shares for many stocks.
        </p>
      )}
      {stocks.some((s) => s.assetType === 'crypto' && s.shares !== null) && (
        <p className="sub" style={{ margin: '8px 0 0' }}>
          Coin amounts are approximate.
        </p>
      )}
      {[...guides.values()].some((g) => g !== null && g.steps.length > 0) && <OrderDisclaimer style={{ marginTop: 8 }} />}
    </section>
  )
}

function Line({
  line,
  run,
  mixed,
  index,
  guide,
}: {
  line: StockLine
  run: Run
  mixed: boolean
  index: number
  guide: OrderPlan | null
}) {
  const coin = line.assetType === 'crypto'
  const about = coin
    ? [line.name, 'Crypto'].filter(Boolean).join(' · ')
    : [line.name, line.market, line.sector].filter(Boolean).join(' · ')
  const pct = (fraction: number) => fmtPct(fraction * 100)
  const exit = coin ? addDays(run.et_date, line.horizonDays) : addWeekdays(run.et_date, line.horizonDays)
  return (
    <li className={`invest-row ${coin ? 'coin' : 'stock'}`} style={{ '--i': index } as CSSProperties}>
      <div className="i-amount">
        <b className="num">{fmtMoney(line.amount)}</b>
        {line.shares !== null && (
          <span className="sub num">{coin ? `≈ ${fmtQty(line.shares)} ${line.symbol}` : `≈ ${line.shares.toFixed(2)} sh`}</span>
        )}
      </div>
      <div className="i-main">
        <div className="i-title">
          <Link className="sym" href={tickerHref(line.symbol, line.assetType)}>
            {line.symbol}
          </Link>
          <span className="sub">{about}</span>
          {mixed && line.qualifies && <span className="chip buy">passes the bar</span>}
        </div>
        <p className="i-line">
          <span className="num">{pct(line.q50)}</span> (likely <span className="num">{pct(line.q10)}</span> to{' '}
          <span className="num">{pct(line.q90)}</span>) over {line.horizonDays} {coin ? 'days' : 'trading days'} vs {line.benchmark} · P(beat){' '}
          <span className="num">{Math.round(line.pBeat * 100)}%</span>
        </p>
        <p className="i-line sub">
          {line.volatility !== null && line.vol60 !== null && (
            <>
              Volatility {line.volatility} ({Math.round(line.vol60 * 100)}%/yr) ·{' '}
            </>
          )}
          exit by ≈ {shortDay(exit)} · round-trip cost {pct(line.cost)}
          {line.market === 'US' && ' (incl. currency fee)'}
          {coin && ' (incl. crypto fee)'}
        </p>
        {guide && <OrderGuide plan={guide} />}
      </div>
    </li>
  )
}
