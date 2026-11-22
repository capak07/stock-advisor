'use client'

import { Bell, Trash2 } from 'lucide-react'
import { useActionState, useCallback, useEffect, useState, useTransition } from 'react'
import { addAlert, deleteAlert, dismissAlert } from '@/app/(app)/ticker/[symbol]/alerts'
import { Drawer } from '@/components/Drawer'
import { useToast } from '@/components/Toast'
import { useFieldErrors } from '@/components/useFieldErrors'
import { alertCurrency, fmtLevel, type AlertDirection } from '@/lib/alert-form'
import type { PriceAlert } from '@/lib/data/monitor'
import { shortDay, todayInToronto } from '@/lib/dates'
import type { AssetType } from '@/lib/portfolio/types'
import type { FormState } from '@/lib/trade-form'

/**
 * The stock page's Alerts button and its glass sheet (spec §7.7): above/below price alerts on this asset; add
 * one, see which are active or hit, dismiss or delete. The form starts from `initialLevel`, `initialDirection`
 * and `initialNote` when a link prefilled it (an exit plan's "Alert me at"), and then the sheet opens by
 * itself; nothing is saved until the owner adds it. Key it on them to re-seed.
 */
export function AlertsCard({
  symbol,
  assetType,
  alerts,
  initialLevel = null,
  initialDirection = null,
  initialNote = null,
}: {
  symbol: string
  assetType: AssetType
  alerts: PriceAlert[]
  initialLevel?: string | null
  initialDirection?: AlertDirection | null
  initialNote?: string | null
}) {
  const toast = useToast()
  const currency = alertCurrency(symbol, assetType)
  const [state, action, pending] = useActionState<FormState, FormData>(addAlert, {})
  const [level, setLevel] = useState(initialLevel ?? '')
  const [note, setNote] = useState(initialNote ?? '')
  const [direction, setDirection] = useState<string>(initialDirection ?? 'above')
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
  const hit = visible.some((a) => a.hitAt)
  const [open, setOpen] = useState(initialLevel !== null || initialDirection !== null || initialNote !== null)
  const close = useCallback(() => setOpen(false), [])

  return (
    <>
      <button
        type="button"
        className="btn btn-secondary"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls="alerts"
        onClick={() => setOpen(true)}
      >
        <Bell />
        Alerts
        {visible.length > 0 && <span className={`count${hit ? ' attention' : ''}`}>{visible.length}</span>}
      </button>
      <Drawer id="alerts" title="Alerts" open={open} onClose={close}>
        <div className="drawer-body">
          <p className="sub" style={{ margin: 0 }}>
            Levels for {symbol} are in {currency}.
          </p>
          {visible.length === 0 ? (
            <p className="sub" style={{ margin: 0 }}>
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
                        Crossed {a.direction} {fmtLevel(a.level)} <span className="sub">{currency}</span> by the last run
                        {a.hitPrice !== null && `, at ${fmtLevel(a.hitPrice)}`} on {shortDay(todayInToronto(new Date(a.hitAt)))}
                        {a.note && <span className="sub"> · {a.note}</span>}
                      </>
                    ) : (
                      <>
                        {a.direction === 'above' ? 'Above' : 'Below'} {fmtLevel(a.level)} <span className="sub">{currency}</span>
                        {a.note && ` · ${a.note}`}
                      </>
                    )}
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

          <form action={action} noValidate>
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
          <p className="sub" style={{ margin: 0 }}>
            Alerts are checked on each run (about 3 a day), not live, and appear only here and on Today.
          </p>
        </div>
      </Drawer>
    </>
  )
}
