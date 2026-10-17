'use client'

import { Plus, X } from 'lucide-react'
import { useActionState, useEffect, useState, useTransition } from 'react'
import { addWatch, removeWatch } from '@/app/(app)/watchlist/actions'
import { useToast } from '@/components/Toast'
import type { AssetType } from '@/lib/portfolio/types'
import type { FormState } from '@/lib/trade-form'
import { WATCH_TYPES, type WatchType } from '@/lib/watch-form'

export interface WatchRow {
  symbol: string
  assetType: AssetType
  name: string | null
  type: 'US' | 'TSX' | 'Crypto'
  price: string | null
}

export function AddWatch() {
  const toast = useToast()
  const [state, action, pending] = useActionState<FormState, FormData>(addWatch, {})
  const [symbol, setSymbol] = useState('')
  const [type, setType] = useState<WatchType>('us')
  const [editedAt, setEditedAt] = useState(0)
  const error = state.errors?.symbol && editedAt <= (state.at ?? 0) ? state.errors.symbol : undefined

  useEffect(() => {
    if (state.ok && state.message) toast(state.message)
  }, [state, toast])
  // A saved symbol clears the box for the next one.
  const [savedAt, setSavedAt] = useState(0)
  if (state.ok && state.at && state.at !== savedAt) {
    setSavedAt(state.at)
    setSymbol('')
  }

  return (
    <form action={action} className="add-row" noValidate>
      <label className={`field ${error ? 'invalid' : ''}`}>
        <span className="sr-only">Symbol</span>
        <input
          className="input num-input"
          name="symbol"
          placeholder="Symbol, e.g. NVDA, SHOP.TO or ETH"
          autoCapitalize="characters"
          value={symbol}
          onChange={(e) => {
            setSymbol(e.target.value)
            setEditedAt(Date.now())
          }}
        />
        <span className="error">{error}</span>
      </label>
      <label className="field">
        <span className="sr-only">Type</span>
        <select className="select" name="type" value={type} onChange={(e) => setType(e.target.value as WatchType)}>
          {WATCH_TYPES.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </select>
      </label>
      <button type="submit" className="btn btn-primary" disabled={pending}>
        <Plus />
        {pending ? 'Adding…' : 'Add'}
      </button>
      {state.message && !state.ok && <span className="sub loss">{state.message}</span>}
    </form>
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
              <span className="sym">{row.symbol}</span>
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
