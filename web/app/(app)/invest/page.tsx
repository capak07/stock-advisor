import { Info, TriangleAlert } from 'lucide-react'
import type { Metadata } from 'next'
import Link from 'next/link'
import type { CSSProperties } from 'react'
import { ownerClient } from '@/lib/auth'
import { loadInvestData } from '@/lib/data/invest'
import { shortDay } from '@/lib/dates'
import { fmtMoney, fmtPct } from '@/lib/format'
import { allocate, type StockLine } from '@/lib/invest/allocate'
import { addWeekdays, parseInvestInputs, type InvestInputs } from '@/lib/invest/inputs'
import { KIND_LABEL, type Run } from '@/lib/runs'
import { tickerHref } from '@/lib/ticker'

export const metadata: Metadata = { title: 'Invest' }

interface Props {
  searchParams: Promise<{ amount?: string | string[]; crypto?: string | string[] }>
}

const NOT_VALIDATED =
  "Not validated: none of these meets the picks' bar today. They're the model's best-ranked, not recommendations."
const PARTLY_VALIDATED =
  "Not validated: only the stocks marked “passes the bar” meet the picks' bar today. The rest are the model's best-ranked, not recommendations."

/**
 * Invest (docs/superpowers/specs/2026-10-27-invest-page-design.md): split an amount over up to five
 * of the newest run's best-ranked stocks and a BTC share. Returns are always excess over the benchmark.
 */
export default async function InvestPage({ searchParams }: Props) {
  const supabase = await ownerClient()
  if (!supabase) return null // the layout is showing the not-the-owner notice
  const inputs = parseInvestInputs(await searchParams)
  const data = await loadInvestData(supabase)

  return (
    <main className="page">
      <div className="enter">
        <h1>Invest</h1>
        <p className="sub">Type an amount to see where it would go today, split over the model&apos;s best-ranked stocks and a share for BTC.</p>
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
        inputs.amount !== null &&
        inputs.cryptoPct !== null && (
          <Result
            run={data.run}
            amount={inputs.amount}
            allocation={allocate({
              amount: inputs.amount,
              cryptoPct: inputs.cryptoPct,
              usdFxFeePct: data.usdFxFeePct,
              candidates: data.candidates,
              held: data.held,
              btcPriceCad: data.btcPriceCad,
            })}
          />
        )
      )}
    </main>
  )
}

function SplitForm({ inputs }: { inputs: InvestInputs }) {
  return (
    <form method="get" action="/invest" className="invest-form" noValidate>
      <label className={`field ${inputs.amountError ? 'invalid' : ''}`}>
        <span>Amount (C$)</span>
        <input
          className="input num-input"
          name="amount"
          inputMode="decimal"
          autoComplete="off"
          placeholder="1,000"
          defaultValue={inputs.amountText}
          aria-invalid={inputs.amountError ? true : undefined}
        />
        <span className="error">{inputs.amountError}</span>
      </label>
      <label className={`field ${inputs.cryptoError ? 'invalid' : ''}`}>
        <span>Crypto share</span>
        <span className="with-unit">
          <input
            className="input num-input"
            name="crypto"
            inputMode="decimal"
            autoComplete="off"
            defaultValue={inputs.cryptoText}
            aria-invalid={inputs.cryptoError ? true : undefined}
          />
          <span className="unit">%</span>
        </span>
        <span className="hint">Goes to BTC</span>
        <span className="error">{inputs.cryptoError}</span>
      </label>
      <button type="submit" className="btn btn-primary">
        Split it
      </button>
    </form>
  )
}

function Result({ run, amount, allocation }: { run: Run; amount: number; allocation: ReturnType<typeof allocate> }) {
  const { stocks, crypto, uninvested, notValidated, evenSplit } = allocation
  const mixed = notValidated && stocks.some((s) => s.qualifies)
  return (
    <section className="card card-pad enter" aria-labelledby="result-h">
      <div className="section-head" style={{ marginBottom: 6 }}>
        <h2 id="result-h">Where {fmtMoney(amount)} would go</h2>
      </div>
      <p className="sub" style={{ margin: '0 0 12px' }}>
        From the {KIND_LABEL[run.kind]} run of {shortDay(run.et_date)} · returns are vs SPY (US) or XIU.TO (TSX), not plain gains
      </p>
      {notValidated && (
        <div className="banner warn" role="alert" style={{ marginBottom: 12 }}>
          <TriangleAlert />
          <div>{mixed ? PARTLY_VALIDATED : NOT_VALIDATED}</div>
        </div>
      )}
      <ul className="invest-list stagger" id="invest-lines">
        {stocks.map((line, i) => (
          <StockRow key={line.symbol} line={line} run={run} mixed={mixed} index={i} />
        ))}
        {crypto.amount > 0 && (
          <li className="invest-row crypto" style={{ '--i': stocks.length } as CSSProperties}>
            <div className="i-amount">
              <b className="num">{fmtMoney(crypto.amount)}</b>
              {crypto.units !== null && <span className="sub num">≈ {crypto.units.toFixed(6)} BTC</span>}
            </div>
            <div className="i-main">
              <div className="i-title">
                <Link className="sym" href={tickerHref('BTC', 'crypto')}>
                  BTC
                </Link>
                <span className="sub">Bitcoin · crypto · no forecast (no crypto model yet)</span>
              </div>
              {crypto.units === null && <p className="i-line sub">Add BTC to your watchlist to see its price.</p>}
            </div>
          </li>
        )}
      </ul>
      {evenSplit && (
        <p className="sub" style={{ margin: '10px 0 0' }}>
          Too few stocks for the 40% cap, so the money is split evenly.
        </p>
      )}
      {uninvested > 0 && (
        <p className="i-uninvested" id="invest-uninvested">
          <b className="num">{fmtMoney(uninvested)}</b> not invested: no stock is expected to beat its benchmark today.
        </p>
      )}
      <div className="invest-foot">
        <b className="num">Total {fmtMoney(amount)}</b>
        <span className="sub">Not financial or tax advice. Forecasts are probabilistic and can be wrong.</span>
      </div>
      {stocks.some((s) => s.shares !== null) && (
        <p className="sub" style={{ margin: '8px 0 0' }}>
          Shares are approximate; Wealthsimple allows fractional shares for many stocks.
        </p>
      )}
    </section>
  )
}

function StockRow({ line, run, mixed, index }: { line: StockLine; run: Run; mixed: boolean; index: number }) {
  const about = [line.name, line.market, line.sector].filter(Boolean).join(' · ')
  const pct = (fraction: number) => fmtPct(fraction * 100)
  return (
    <li className="invest-row stock" style={{ '--i': index } as CSSProperties}>
      <div className="i-amount">
        <b className="num">{fmtMoney(line.amount)}</b>
        {line.shares !== null && <span className="sub num">≈ {line.shares.toFixed(2)} sh</span>}
      </div>
      <div className="i-main">
        <div className="i-title">
          <Link className="sym" href={tickerHref(line.symbol, 'stock')}>
            {line.symbol}
          </Link>
          <span className="sub">{about}</span>
          {mixed && line.qualifies && <span className="chip buy">passes the bar</span>}
        </div>
        <p className="i-line">
          <span className="num">{pct(line.q50)}</span> (likely <span className="num">{pct(line.q10)}</span> to{' '}
          <span className="num">{pct(line.q90)}</span>) over {line.horizonDays} trading days vs {line.benchmark} · P(beat){' '}
          <span className="num">{Math.round(line.pBeat * 100)}%</span>
        </p>
        <p className="i-line sub">
          {line.volatility !== null && line.vol60 !== null && (
            <>
              Volatility {line.volatility} ({Math.round(line.vol60 * 100)}%/yr) ·{' '}
            </>
          )}
          exit by ≈ {shortDay(addWeekdays(run.et_date, line.horizonDays))} · round-trip cost {pct(line.cost)}
          {line.market === 'US' && ' (incl. currency fee)'}
        </p>
      </div>
    </li>
  )
}
