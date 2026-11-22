'use client'

import { X } from 'lucide-react'
import Link from 'next/link'
import { useState, useTransition } from 'react'
import { addWatch, removeWatch } from '@/app/(app)/watchlist/actions'
import { LowRankChip } from '@/components/LowRankChip'
import { OrderGuide } from '@/components/OrderGuide'
import { RangeBar } from '@/components/picks/RangeBar'
import { SymbolSearch } from '@/components/SymbolSearch'
import { useToast } from '@/components/Toast'
import { fmtPct } from '@/lib/format'
import type { Guide } from '@/lib/guidance'
import { edgeWords } from '@/lib/outlook'
import { assetKey, type AssetType } from '@/lib/portfolio/types'
import type { SearchItem } from '@/lib/symbol-search'
import { tickerHref } from '@/lib/ticker'
import { type HeldGroup, VERDICT_LABEL, type Verdict } from '@/lib/verdicts'
import { PICK_FROM_LIST } from '@/lib/watch-form'

export interface WatchRow {
  symbol: string
  assetType: AssetType
  name: string | null
  type: 'US' | 'TSX' | 'Crypto'
  price: string | null
  /** The last close's move from the close before, in percent; null without two closes. */
  move: number | null
  /** The latest published run's verdict; null when the symbol was added after it. */
  verdict: Verdict | null
  /** Held at that run: My Portfolio's action, shown instead of the verdict. */
  held: { group: HeldGroup; label: string } | null
  why: string | null
  /** How to place a Buy; null for other verdicts. */
  guide: Guide | null
  /** Low model rank in the latest run: how many US stocks it ranked; null when not flagged. */
  lowRank: number | null
  /** The run's forecast at the verdict's horizon (else the one closest to 21 days); null when held or not forecast. */
  outlook: { benchmark: string; horizon: number; pBeat: number; q10: number; q50: number; q90: number } | null
}

/** Search the stock and coin lists; picking a match watches it. `watched` holds asset keys. */
export function AddWatch({ watched }: { watched: string[] }) {
  const toast = useToast()
  const [pending, startTransition] = useTransition()
  const [error, setError] = useState<string | null>(null)
  const watching = new Set(watched)

  const add = (item: SearchItem) => {
    if (pending) return
    setError(null)
    startTransition(async () => {
      const result = await addWatch(item.symbol, item.assetType)
      if (result.ok && result.message) toast(result.message)
      else setError(result.errors?.symbol ?? result.message ?? null)
    })
  }

  return (
    <div className={`field ${error ? 'invalid' : ''}`}>
      <SymbolSearch
        label="Symbol"
        placeholder="Company, coin or ticker, e.g. Shopify, Ethereum or RY.TO"
        invalid={error !== null}
        emptyText="No listed stock or coin matches."
        unavailable={(item) => (watching.has(assetKey(item.assetType, item.symbol)) ? 'On your watchlist' : null)}
        onPick={add}
        onNoMatch={(_, ready) => ready && setError(PICK_FROM_LIST)}
        onEdit={() => setError(null)}
      />
      <span className="error">{error}</span>
      {pending && <span className="hint">Adding…</span>}
    </div>
  )
}

/** The verdict in words with its chance, horizon and likely range (spec §7.6). */
function Outlook({ row, outlook }: { row: WatchRow; outlook: NonNullable<WatchRow['outlook']> }) {
  const n = outlook.horizon
  return (
    <>
      <div className="w-line">
        <span className={`chip ${row.verdict === 'buy' || row.verdict === 'avoid' ? row.verdict : 'neutral'}`}>{edgeWords(row.verdict)}</span>
        {row.lowRank !== null && <LowRankChip scored={row.lowRank} />}
        <span className="w-odds">
          <b>{Math.round(outlook.pBeat * 100)}%</b> to beat {outlook.benchmark} over {n} days
        </span>
      </div>
      <div className="w-range">
        <RangeBar q10={outlook.q10} q50={outlook.q50} q90={outlook.q90} benchmark={outlook.benchmark} />
        <div className="range-lab num">
          <span>{fmtPct(outlook.q10 * 100)}</span>
          <span>likely {n}-day range</span>
          <span>{fmtPct(outlook.q90 * 100)}</span>
        </div>
      </div>
    </>
  )
}

/** A held row's Portfolio action, or a row's verdict as before the outlook (a coin not forecast, a new symbol). */
function Call({ row }: { row: WatchRow }) {
  return (
    <div className="w-line">
      {row.held ? (
        <span className={`chip ${row.held.group}`}>{row.held.label}</span>
      ) : row.verdict ? (
        <span className={`chip ${row.verdict}`}>{VERDICT_LABEL[row.verdict]}</span>
      ) : (
        <span className="chip hold">New</span>
      )}
      {row.lowRank !== null && <LowRankChip scored={row.lowRank} />}
    </div>
  )
}

/**
 * Before the model: symbol, price, today's move. With verdicts (watchlist_2.html): a row that is not
 * held also shows its chance, horizon and likely range; a held one shows My Portfolio's action instead.
 */
export function WatchList({ rows, withVerdicts = false }: { rows: WatchRow[]; withVerdicts?: boolean }) {
  const toast = useToast()
  const [removing, setRemoving] = useState<string | null>(null)
  const [, startTransition] = useTransition()

  const remove = (row: WatchRow) => {
    setRemoving(row.symbol)
    startTransition(async () => {
      const result = await removeWatch(row.symbol, row.assetType)
      setRemoving(null)
      if (result.message) toast(result.message)
    })
  }

  if (rows.length === 0) {
    return (
      <p className="sub" style={{ margin: 0 }}>
        Nothing yet. Add a US stock, a TSX stock or a coin above.
      </p>
    )
  }
  return (
    <div className="watch-list">
      {rows.map((row) => {
        const outlook = row.held ? null : row.outlook
        return (
          <div key={`${row.assetType}:${row.symbol}`} className={`watch-row ${removing === row.symbol ? 'removing' : ''}`}>
            <div className="w-top">
              <div className="w-id">
                <span className="w-sym">
                  <Link className="sym" href={tickerHref(row.symbol, row.assetType)}>
                    {row.symbol}
                  </Link>
                  <span className="w-type">{row.type}</span>
                </span>
                {row.name && <span className="name">{row.name}</span>}
              </div>
              <div className="w-quote">
                <span className="num w-price">{row.price ?? <span className="sub">next run</span>}</span>
                {row.move !== null && (
                  <span className={`num w-move ${moveTone(row.move)}`} title="Move at the last close">
                    {fmtPct(row.move)}
                  </span>
                )}
              </div>
              {withVerdicts && (
                <div className="w-v">
                  {outlook ? <Outlook row={row} outlook={outlook} /> : <Call row={row} />}
                  <span className="w-detail sub">{row.why ?? 'Gets its first verdict at the next run'}</span>
                </div>
              )}
              <button
                type="button"
                className="icon-btn w-x"
                aria-label={`Remove ${row.symbol}`}
                disabled={removing !== null}
                onClick={() => remove(row)}
              >
                <X />
              </button>
            </div>
            {withVerdicts && row.verdict === 'buy' && !row.held && row.guide && (
              <OrderGuide plan={row.guide.plan} caption={row.guide.caption} fold="closed" />
            )}
          </div>
        )
      })}
    </div>
  )
}

/** Gain or loss colour for a move that rounds away from zero. */
const moveTone = (move: number): string => (Number(move.toFixed(1)) === 0 ? '' : move > 0 ? 'gain' : 'loss')
