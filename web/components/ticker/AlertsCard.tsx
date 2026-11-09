'use client'

import { Bell, Trash2 } from 'lucide-react'
import { useActionState, useEffect, useState, useTransition } from 'react'
import { addAlert, deleteAlert, dismissAlert } from '@/app/(app)/ticker/[symbol]/alerts'
import { useToast } from '@/components/Toast'
import { useFieldErrors } from '@/components/useFieldErrors'
import { alertCurrency, fmtLevel } from '@/lib/alert-form'
import type { PriceAlert } from '@/lib/data/monitor'
import { shortDay, todayInToronto } from '@/lib/dates'
import type { AssetType } from '@/lib/portfolio/types'
import type { FormState } from '@/lib/trade-form'

/** Above/below price alerts on this asset: add one, see which are active or hit, dismiss or delete. */
export function AlertsCard({ symbol, assetType, alerts }: { symbol: string; assetType: AssetType; alerts: PriceAlert[] }) {
  const toast = useToast()
  const currency = alertCurrency(symbol, assetType)
  const [state, action, pending] = useActionState<FormState, FormData>(addAlert, {})
  const [level, setLevel] = useState('')
  const [note, setNote] = useState('')
  const [direction, setDirection] = useState('above')
  const { error, touch } = useFieldErrors(state)
  const [busy, startTransition] = useTransition()

  // clear the fields once an answer says the alert was saved (adjusting state while rendering)
  const [seen, setSeen] = useState(state)
  if (state !== seen) {
    setSeen(state)
    if (state.ok) {
      setLevel('')
      setNote('')
    }
  }
  useEffect(() => {
    if (state.message) toast(state.message)
  }, [state, toast])

  const run = (act: () => Promise<FormState>) =>
    startTransition(async () => {
      const result = await act()
      if (result.message) toast(result.message)
    })

  const visible = alerts.filter((a) => !a.dismissedAt)

  return (
    <section className="card card-pad enter" aria-labelledby="alerts-h" id="alerts">
      <div className="section-head" style={{ marginBottom: 4 }}>
        <h2 id="alerts-h">Alerts</h2>
        <span className="sub">{currency}</span>
      </div>
      {visible.length === 0 ? (
        <p className="sub" style={{ margin: '6px 0 0' }}>
          No alerts on {symbol}.
        </p>
      ) : (
        <div>
          {visible.map((a) => (
            <div key={a.id} className="news-item" data-testid="alert-row" data-hit={a.hitAt ? 'true' : 'false'}>
              <span className={`badge${a.hitAt ? ' attention' : ''}`}>{a.hitAt ? 'Hit' : 'Active'}</span>
              <span>
                {a.hitAt ? (
                  <>
                    Crossed {a.direction} {fmtLevel(a.level)} by the last run
                    {a.hitPrice !== null && `, at ${fmtLevel(a.hitPrice)}`} on {shortDay(todayInToronto(new Date(a.hitAt)))}
                  </>
                ) : (
                  <>
                    {a.direction === 'above' ? 'Above' : 'Below'} {fmtLevel(a.level)}
                    {a.note && ` · ${a.note}`}
                  </>
                )}{' '}
                <span className="sub">{currency}</span>
                {a.hitAt && a.note && <span className="sub"> · {a.note}</span>}
              </span>
              <span />
              <span className="flex gap-2">
                {a.hitAt && (
                  <button type="button" className="btn btn-sm btn-secondary" disabled={busy} onClick={() => run(() => dismissAlert(a.id))}>
                    Dismiss
                  </button>
                )}
                <button
                  type="button"
                  className="btn btn-sm btn-secondary"
                  disabled={busy}
                  aria-label={`Delete alert ${a.direction} ${fmtLevel(a.level)}`}
                  onClick={() => run(() => deleteAlert(a.id))}
                >
                  <Trash2 />
                  Delete
                </button>
              </span>
            </div>
          ))}
        </div>
      )}

      <form action={action} style={{ marginTop: 14 }} noValidate>
        <input type="hidden" name="symbol" value={symbol} />
        <input type="hidden" name="assetType" value={assetType} />
        <div className="flex flex-wrap items-start gap-3">
          <label className="field">
            <span>Alert when the price is</span>
            <select className="input" name="direction" value={direction} onChange={(e) => setDirection(e.target.value)}>
              <option value="above">Above</option>
              <option value="below">Below</option>
            </select>
          </label>
          <label className={`field ${error('level') ? 'invalid' : ''}`}>
            <span>Level ({currency})</span>
            <input
              className="input num-input"
              name="level"
              inputMode="decimal"
              value={level}
              onChange={(e) => {
                setLevel(e.target.value)
                touch('level')
              }}
            />
            <span className="error">{error('level')}</span>
          </label>
          <label className={`field ${error('note') ? 'invalid' : ''}`} style={{ flex: '1 1 180px' }}>
            <span>Note (optional)</span>
            <input
              className="input"
              name="note"
              value={note}
              onChange={(e) => {
                setNote(e.target.value)
                touch('note')
              }}
            />
            <span className="error">{error('note')}</span>
          </label>
          <button type="submit" className="btn btn-primary" disabled={pending} style={{ marginTop: 22 }}>
            <Bell />
            {pending ? 'Saving…' : 'Add alert'}
          </button>
        </div>
        {assetType === 'crypto' && (
          <p className="sub" style={{ margin: '8px 0 0' }}>
            Coin alerts use the USD price.
          </p>
        )}
        {(error('symbol') || error('direction')) && <p className="error">{error('symbol') ?? error('direction')}</p>}
      </form>
      <p className="sub" style={{ margin: '10px 0 0' }}>
        Alerts are checked on each run (about 3 a day), not live, and appear only here and on My Portfolio.
      </p>
    </section>
  )
}
