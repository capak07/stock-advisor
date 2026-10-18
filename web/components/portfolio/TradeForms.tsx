'use client'

import { FileUp, Minus, Plus, TriangleAlert } from 'lucide-react'
import { useActionState, useCallback, useEffect, useMemo, useState } from 'react'
import { addBuy, addSell } from '@/app/(app)/trades'
import { Drawer } from '@/components/Drawer'
import { ImportDrawer } from '@/components/portfolio/ImportDrawer'
import { useFieldErrors } from '@/components/useFieldErrors'
import { useToast } from '@/components/Toast'
import { shortDay } from '@/lib/dates'
import { fmtMoney, fmtQty } from '@/lib/format'
import { FxRates, type FxRate } from '@/lib/portfolio/lookup'
import { ACCOUNTS, ACCOUNT_LABELS, TAXABLE } from '@/lib/portfolio/types'
import type { Account, Trade } from '@/lib/portfolio/types'
import type { SellOption } from '@/lib/portfolio/view'
import { normalizeSymbol, tradeCurrency } from '@/lib/symbols'
import { parseAmount, type FormState } from '@/lib/trade-form'

function Foot({ pending, label, icon, onCancel }: { pending: boolean; label: string; icon?: React.ReactNode; onCancel: () => void }) {
  return (
    <div className="drawer-foot">
      <button type="button" className="btn btn-secondary" onClick={onCancel}>
        Cancel
      </button>
      <button type="submit" className="btn btn-primary" disabled={pending}>
        {icon}
        {pending ? 'Saving…' : label}
      </button>
    </div>
  )
}

/** On success: toast, then close. */
function useDone(state: FormState, onDone: (message: string) => void) {
  useEffect(() => {
    if (state.ok && state.message) onDone(state.message)
  }, [state, onDone])
}

function Field({
  label,
  error,
  hint,
  children,
}: {
  label: React.ReactNode
  error?: string
  hint?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <label className={`field ${error ? 'invalid' : ''}`}>
      <span>{label}</span>
      {children}
      {hint && <span className="hint">{hint}</span>}
      <span className="error">{error}</span>
    </label>
  )
}

/** The Bank of Canada rate for a day, as the rate field's default. */
const useBocRate = (rates: FxRate[], day: string) => {
  const fx = useMemo(() => new FxRates(rates), [rates])
  const rate = fx.on(day)
  const from = fx.rates.findLast((r) => r.day <= day)?.day ?? null
  return { rate: rate === null ? '' : rate.toFixed(4), from }
}

function FormMessage({ state }: { state: FormState }) {
  if (!state.message || state.ok) return null
  return (
    <div className="banner danger" role="alert">
      <TriangleAlert />
      <div>{state.message}</div>
    </div>
  )
}

interface FormProps {
  rates: FxRate[]
  today: string
  onDone: (message: string) => void
  onCancel: () => void
}

function BuyForm({ rates, today, onDone, onCancel }: FormProps) {
  const [state, action, pending] = useActionState<FormState, FormData>(addBuy, {})
  const { error, touch, editedSince } = useFieldErrors(state)
  useDone(state, onDone)
  const [account, setAccount] = useState<Account>('tfsa')
  const [symbol, setSymbol] = useState('')
  const [qty, setQty] = useState('')
  const [price, setPrice] = useState('')
  const [day, setDay] = useState(today)
  const [rate, setRate] = useState<string | null>(null)
  const [notes, setNotes] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const currency = tradeCurrency(account === 'crypto' ? 'crypto' : 'stock', normalizeSymbol(symbol))
  const boc = useBocRate(rates, day)
  // The unlisted-symbol question stands until the symbol changes.
  const askConfirm = state.confirm && !editedSince('symbol') ? state.confirm : null

  return (
    <form action={action} style={{ display: 'contents' }} noValidate>
      <div className="drawer-body">
        <FormMessage state={state} />
        <Field label="Account" error={error('account')}>
          <select
            className="select"
            name="account"
            value={account}
            onChange={(e) => {
              setAccount(e.target.value as Account)
              touch('account')
            }}
          >
            {ACCOUNTS.map((a) => (
              <option key={a} value={a}>
                {ACCOUNT_LABELS[a]}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Symbol" error={error('symbol')} hint="US: AAPL · TSX: RY.TO · crypto: BTC">
          <input
            className="input num-input"
            name="symbol"
            placeholder="AAPL, RY.TO or BTC"
            autoCapitalize="characters"
            value={symbol}
            onChange={(e) => {
              setSymbol(e.target.value)
              setConfirmed(false)
              touch('symbol')
            }}
          />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Quantity" error={error('qty')}>
            <input
              className="input num-input"
              name="qty"
              inputMode="decimal"
              placeholder="10"
              value={qty}
              onChange={(e) => {
                setQty(e.target.value)
                touch('qty')
              }}
            />
          </Field>
          <Field label={`Price (${currency})`} error={error('price')}>
            <input
              className="input num-input"
              name="price"
              inputMode="decimal"
              placeholder="184.00"
              value={price}
              onChange={(e) => {
                setPrice(e.target.value)
                touch('price')
              }}
            />
          </Field>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Date" error={error('day')}>
            <input
              className="input num-input"
              type="date"
              name="day"
              max={today}
              value={day}
              onChange={(e) => {
                setDay(e.target.value)
                touch('day')
              }}
            />
          </Field>
          {currency === 'USD' && (
            <Field
              label="USD/CAD rate"
              error={error('fxRate')}
              hint={boc.from ? `Bank of Canada, ${shortDay(boc.from)}. Enter Wealthsimple's rate to include its fee.` : 'Enter the rate you paid.'}
            >
              <input
                className="input num-input"
                name="fxRate"
                inputMode="decimal"
                value={rate ?? boc.rate}
                onChange={(e) => {
                  setRate(e.target.value)
                  touch('fxRate')
                }}
              />
            </Field>
          )}
        </div>
        <Field
          label={
            <>
              Notes <span className="muted">(optional)</span>
            </>
          }
          error={error('notes')}
        >
          <input
            className="input"
            name="notes"
            placeholder="Why you bought"
            value={notes}
            onChange={(e) => {
              setNotes(e.target.value)
              touch('notes')
            }}
          />
        </Field>
        {askConfirm && (
          <div className="banner warn">
            <TriangleAlert />
            <div style={{ display: 'grid', gap: 8 }}>
              <span>{askConfirm}</span>
              <label style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <input
                  type="checkbox"
                  name="confirmUnlisted"
                  checked={confirmed}
                  onChange={(e) => setConfirmed(e.target.checked)}
                />
                Save it anyway
              </label>
            </div>
          </div>
        )}
      </div>
      <Foot pending={pending} label="Save buy" icon={<Plus />} onCancel={onCancel} />
    </form>
  )
}

function SellForm({ options, rates, today, onDone, onCancel }: FormProps & { options: SellOption[] }) {
  const [state, action, pending] = useActionState<FormState, FormData>(addSell, {})
  const { error, touch } = useFieldErrors(state)
  useDone(state, onDone)
  const [key, setKey] = useState(options[0]?.key ?? '')
  const option = options.find((o) => o.key === key) ?? null
  const [qty, setQty] = useState(option ? String(option.qty) : '')
  const [price, setPrice] = useState('')
  const [day, setDay] = useState(today)
  const [rate, setRate] = useState<string | null>(null)
  const boc = useBocRate(rates, day)
  const usd = option?.currency === 'USD'

  const q = parseAmount(qty)
  const p = parseAmount(price)
  const r = usd ? parseAmount(rate ?? boc.rate) : 1
  const gain =
    option && q !== null && p !== null && r !== null && q > 0 && q <= option.qty + 1e-9
      ? q * p * r - (option.costCad * q) / option.qty
      : null

  return (
    <form action={action} style={{ display: 'contents' }} noValidate>
      <div className="drawer-body">
        <FormMessage state={state} />
        <Field label="Holding" error={error('holding')}>
          <select
            className="select"
            name="holding"
            value={key}
            onChange={(e) => {
              const next = options.find((o) => o.key === e.target.value)
              setKey(e.target.value)
              setQty(next ? String(next.qty) : '')
              setRate(null)
              touch('holding')
            }}
          >
            {options.map((o) => (
              <option key={o.key} value={o.key}>
                {`${o.symbol} · ${ACCOUNT_LABELS[o.account]} · ${fmtQty(o.qty)}${o.assetType === 'stock' ? ' shares' : ''}`}
              </option>
            ))}
          </select>
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Quantity" error={error('qty')}>
            <input
              className="input num-input"
              name="qty"
              inputMode="decimal"
              value={qty}
              onChange={(e) => {
                setQty(e.target.value)
                touch('qty')
              }}
            />
          </Field>
          <Field label={`Price (${option?.currency ?? 'CAD'})`} error={error('price')}>
            <input
              className="input num-input"
              name="price"
              inputMode="decimal"
              placeholder="141.00"
              value={price}
              onChange={(e) => {
                setPrice(e.target.value)
                touch('price')
              }}
            />
          </Field>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Date" error={error('day')}>
            <input
              className="input num-input"
              type="date"
              name="day"
              max={today}
              value={day}
              onChange={(e) => {
                setDay(e.target.value)
                touch('day')
              }}
            />
          </Field>
          {usd && (
            <Field
              label="USD/CAD rate"
              error={error('fxRate')}
              hint={boc.from ? `Bank of Canada, ${shortDay(boc.from)}` : 'Enter the rate you got.'}
            >
              <input
                className="input num-input"
                name="fxRate"
                inputMode="decimal"
                value={rate ?? boc.rate}
                onChange={(e) => {
                  setRate(e.target.value)
                  touch('fxRate')
                }}
              />
            </Field>
          )}
        </div>
        {option && gain !== null && (
          <div className="card card-pad" style={{ background: 'var(--muted)' }}>
            <span className="label">At average cost</span>
            <div className={`num ${gain < 0 ? 'loss' : 'gain'}`} style={{ fontSize: 18, fontWeight: 600, marginTop: 6 }}>
              {fmtMoney(gain, { signed: true })} realized
            </div>
            <p className="sub" style={{ margin: '4px 0 0' }}>
              {!TAXABLE.has(option.account)
                ? `In a ${ACCOUNT_LABELS[option.account]}, gains and losses aren't taxed.`
                : gain >= 0
                  ? `Taxable: est. ${fmtMoney(gain * 0.5, { signed: true })} at 50% inclusion.`
                  : `Buying ${option.symbol} within 30 days before or after this sale denies the loss.`}{' '}
              Not tax advice.
            </p>
          </div>
        )}
      </div>
      <Foot pending={pending} label="Save sell" onCancel={onCancel} />
    </form>
  )
}

/** The Import, Sell and Buy buttons in the page head, and their drawers. */
export function TradeButtons({
  sellable,
  rates,
  today,
  existing,
}: {
  sellable: SellOption[]
  rates: FxRate[]
  today: string
  /** Trades already recorded, so an import can skip them. */
  existing: Trade[]
}) {
  const toast = useToast()
  const [open, setOpen] = useState<'buy' | 'sell' | 'import' | null>(null)
  // Each opening starts a fresh form.
  const [round, setRound] = useState(0)
  const show = (which: 'buy' | 'sell' | 'import') => {
    setRound((n) => n + 1)
    setOpen(which)
  }
  const close = useCallback(() => setOpen(null), [])
  const done = useCallback(
    (message: string) => {
      setOpen(null)
      toast(message)
    },
    [toast],
  )
  return (
    <>
      <div className="flex flex-wrap gap-2">
        <button type="button" className="btn btn-secondary" onClick={() => show('import')}>
          <FileUp />
          Import file
        </button>
        {sellable.length > 0 && (
          <button type="button" className="btn btn-secondary" onClick={() => show('sell')}>
            <Minus />
            Sell
          </button>
        )}
        <button type="button" className="btn btn-primary" onClick={() => show('buy')}>
          <Plus />
          Buy
        </button>
      </div>
      <Drawer id="buy-drawer" title="Add a buy" open={open === 'buy'} onClose={close}>
        <BuyForm key={`buy-${round}`} rates={rates} today={today} onDone={done} onCancel={close} />
      </Drawer>
      <Drawer id="sell-drawer" title="Add a sell" open={open === 'sell'} onClose={close}>
        <SellForm key={`sell-${round}`} options={sellable} rates={rates} today={today} onDone={done} onCancel={close} />
      </Drawer>
      <ImportDrawer
        open={open === 'import'}
        round={round}
        existing={existing}
        rateFrom={rates[0]?.day ?? null}
        today={today}
        onClose={close}
        onDone={done}
      />
    </>
  )
}
