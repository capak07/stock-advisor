'use client'

import { useActionState, useEffect, useState, useSyncExternalStore } from 'react'
import { saveSettings } from '@/app/(app)/settings/actions'
import { Tabs } from '@/components/Tabs'
import { useToast } from '@/components/Toast'
import { useFieldErrors } from '@/components/useFieldErrors'
import { applyTheme, savedTheme, type ThemeChoice } from '@/lib/theme'
import type { FormState } from '@/lib/trade-form'

export interface SettingsValues {
  usd_fx_fee_pct: string
  crypto_fee_pct: string
  tfsa_round_trips_warn: string
  tfsa_short_hold_share_warn: string
}

const FIELDS: { name: keyof SettingsValues; title: string; help: string; unit: string; mode: 'decimal' | 'numeric'; section: 'costs' | 'tfsa' }[] = [
  {
    name: 'usd_fx_fee_pct',
    title: 'USD conversion fee',
    help: 'Charged on each US buy and each US sell. A US pick must beat twice this, plus the spread.',
    unit: '% each way',
    mode: 'decimal',
    section: 'costs',
  },
  {
    name: 'crypto_fee_pct',
    title: 'Crypto spread',
    help: "Wealthsimple's crypto spread, paid on the way in and out.",
    unit: '% each way',
    mode: 'decimal',
    section: 'costs',
  },
  {
    name: 'tfsa_round_trips_warn',
    title: 'Round trips a year',
    help: 'Warn as TFSA buy-and-sell round trips in the last 12 months approach this.',
    unit: 'a year',
    mode: 'numeric',
    section: 'tfsa',
  },
  {
    name: 'tfsa_short_hold_share_warn',
    title: 'Short holds',
    help: 'Warn when this share of holds over 12 months lasted under 30 days.',
    unit: '% of holds',
    mode: 'numeric',
    section: 'tfsa',
  },
]

export function CostsForm({ initial, changed }: { initial: SettingsValues; changed: string }) {
  const toast = useToast()
  const [state, action, pending] = useActionState<FormState, FormData>(saveSettings, {})
  const [values, setValues] = useState(initial)
  const { error, touch } = useFieldErrors(state)
  useEffect(() => {
    if (state.ok && state.message) toast(state.message)
  }, [state, toast])

  const field = (f: (typeof FIELDS)[number]) => (
    <label key={f.name} className={`setting field ${error(f.name) ? 'invalid' : ''}`}>
      <span>
        <strong>{f.title}</strong>
        <p>{f.help}</p>
      </span>
      <span className="with-unit">
        <input
          className="input num-input"
          name={f.name}
          inputMode={f.mode}
          value={values[f.name]}
          onChange={(e) => {
            setValues((v) => ({ ...v, [f.name]: e.target.value }))
            touch(f.name)
          }}
        />
        <span className="unit">{f.unit}</span>
        <span className="error">{error(f.name)}</span>
      </span>
    </label>
  )

  return (
    <form className="card card-pad enter" action={action} noValidate>
      <h2 style={{ marginBottom: 4 }}>Costs</h2>
      {FIELDS.filter((f) => f.section === 'costs').map(field)}
      <h2 style={{ margin: '18px 0 4px' }}>TFSA trading guideline</h2>
      <p className="sub" style={{ margin: '0 0 4px' }}>
        The CRA can tax frequent TFSA trading as business income. There&apos;s no official cutoff; these only set when
        warnings appear. Not tax advice.
      </p>
      {FIELDS.filter((f) => f.section === 'tfsa').map(field)}
      {state.message && !state.ok && <p className="sub loss">{state.message}</p>}
      <div className="flex items-center justify-between gap-3 flex-wrap" style={{ marginTop: 14 }}>
        <span className="sub">Last changed {changed}</span>
        <button type="submit" className="btn btn-primary" disabled={pending}>
          {pending ? 'Saving…' : 'Save'}
        </button>
      </div>
    </form>
  )
}

const THEME_TABS = [
  { value: 'system', label: 'System' },
  { value: 'light', label: 'Light' },
  { value: 'dark', label: 'Dark' },
] as const

const noop = () => () => {}

/** Saved on this device only (localStorage), as in the mockups. */
export function ThemeTabs() {
  const stored = useSyncExternalStore(noop, savedTheme, () => 'system' as ThemeChoice)
  const [choice, setChoice] = useState<ThemeChoice | null>(null)
  return (
    <Tabs
      items={THEME_TABS}
      value={choice ?? stored}
      label="Theme"
      onChange={(value) => {
        setChoice(value)
        applyTheme(value)
      }}
    />
  )
}
