'use client'

import { X } from 'lucide-react'
import Link from 'next/link'
import { useState, useTransition } from 'react'
import { addWatch, removeWatch } from '@/app/(app)/watchlist/actions'
import { OrderGuide } from '@/components/OrderGuide'
import { SymbolSearch } from '@/components/SymbolSearch'
import { useToast } from '@/components/Toast'
import type { Guide } from '@/lib/guidance'
import { assetKey, type AssetType } from '@/lib/portfolio/types'
import type { SearchItem } from '@/lib/symbol-search'
import { tickerHref } from '@/lib/ticker'
import { VERDICT_LABEL, type Verdict } from '@/lib/verdicts'
import { PICK_FROM_LIST } from '@/lib/watch-form'

export interface WatchRow {
  symbol: string
  assetType: AssetType
  name: string | null
  type: 'US' | 'TSX' | 'Crypto'
  price: string | null
  /** The latest published run's verdict; null when the symbol was added after it. */
  verdict: Verdict | null
  why: string | null
  /** How to place a Buy; null for other verdicts. */
  guide: Guide | null
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

/** Before the model: symbol, type, price. With verdicts: also the verdict and why (watchlist_1.html). */
export function WatchList({ rows, withVerdicts = false }: { rows: WatchRow[]; withVerdicts?: boolean }) {
  const plain = withVerdicts ? '' : 'plain'
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
    <>
      <div className={`watch-head ${plain} label`}>
        <span>Symbol</span>
        <span>Type</span>
        {withVerdicts && (
          <>
            <span>Verdict</span>
            <span>Why</span>
          </>
        )}
        <span style={{ textAlign: 'right' }}>Price</span>
        <span />
      </div>
      <div>
        {rows.map((row) => (
          <div
            key={`${row.assetType}:${row.symbol}`}
            className={`watch-row ${plain} ${removing === row.symbol ? 'removing' : ''}`}
          >
            <span className="w-sym">
              <Link className="sym" href={tickerHref(row.symbol, row.assetType)}>
                {row.symbol}
              </Link>
              {row.name && (
                <>
                  <br />
                  <span className="sub">{row.name}</span>
                </>
              )}
            </span>
            <span className="w-type sub">{row.type}</span>
            {withVerdicts && (
              <>
                <span className="w-verdict">
                  {row.verdict ? (
                    <span className={`chip ${row.verdict}`}>{VERDICT_LABEL[row.verdict]}</span>
                  ) : (
                    <span className="chip hold">New</span>
                  )}
                </span>
                <span className="w-why">
                  <span className="w-detail sub">{row.why ?? 'Gets its first verdict at the next run'}</span>
                  {row.verdict === 'buy' && row.guide && <OrderGuide plan={row.guide.plan} caption={row.guide.caption} />}
                </span>
              </>
            )}
            <span className="w-price num" style={{ textAlign: 'right' }}>
              {row.price ?? <span className="sub">next run</span>}
            </span>
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
        ))}
      </div>
    </>
  )
}
