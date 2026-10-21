'use client'

import { X } from 'lucide-react'
import Link from 'next/link'
import { useState, useTransition } from 'react'
import { addWatch, removeWatch } from '@/app/(app)/watchlist/actions'
import { SymbolSearch } from '@/components/SymbolSearch'
import { useToast } from '@/components/Toast'
import { assetKey, type AssetType } from '@/lib/portfolio/types'
import type { SearchItem } from '@/lib/symbol-search'
import { tickerHref } from '@/lib/ticker'
import { PICK_FROM_LIST } from '@/lib/watch-form'

export interface WatchRow {
  symbol: string
  assetType: AssetType
  name: string | null
  type: 'US' | 'TSX' | 'Crypto'
  price: string | null
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

export function WatchList({ rows }: { rows: WatchRow[] }) {
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
      <div className="watch-head plain label">
        <span>Symbol</span>
        <span>Type</span>
        <span style={{ textAlign: 'right' }}>Price</span>
        <span />
      </div>
      <div>
        {rows.map((row) => (
          <div
            key={`${row.assetType}:${row.symbol}`}
            className={`watch-row plain ${removing === row.symbol ? 'removing' : ''}`}
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
