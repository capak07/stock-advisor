'use client'

import { useState } from 'react'
import { STOCKS, type Hold } from '@/lib/invest/allocate'
import { holdsFor, type AssetChoice, type InvestInputs } from '@/lib/invest/inputs'

/** The amount, the kind of asset, how many names and how long to hold. A GET form, so the result is a URL. */
export function SplitForm({ inputs }: { inputs: InvestInputs }) {
  const [asset, setAsset] = useState<AssetChoice>(inputs.asset ?? 'stocks')
  const [hold, setHold] = useState(inputs.hold ?? 'any')
  const holds = holdsFor(asset)
  const noun = asset === 'crypto' ? 'coin' : 'stock'
  const nouns = asset === 'crypto' ? 'coins' : 'stocks'

  const chooseAsset = (next: AssetChoice) => {
    setAsset(next)
    const allowed = new Set<string>(holdsFor(next).map((h) => h.value))
    if (!allowed.has(hold)) setHold('any')
  }

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
      <label className={`field ${inputs.assetError ? 'invalid' : ''}`}>
        <span>Invest in</span>
        <select className="select" name="asset" value={asset} onChange={(e) => chooseAsset(e.target.value as AssetChoice)}>
          <option value="stocks">Stocks</option>
          <option value="crypto">Crypto</option>
        </select>
        <span className="error">{inputs.assetError}</span>
      </label>
      <label className={`field ${inputs.stocksError ? 'invalid' : ''}`}>
        <span>Number of {nouns}</span>
        <select className="select" name="stocks" defaultValue={String(inputs.stocks ?? STOCKS)}>
          {Array.from({ length: STOCKS }, (_, i) => i + 1).map((n) => (
            <option key={n} value={n}>
              {n === 1 ? `1 (all in the top ${noun})` : n}
            </option>
          ))}
        </select>
        <span className="error">{inputs.stocksError}</span>
      </label>
      <label className={`field ${inputs.holdError ? 'invalid' : ''}`}>
        <span>How long to hold</span>
        <select className="select" name="hold" value={hold} onChange={(e) => setHold(e.target.value as Hold)}>
          {holds.map((h) => (
            <option key={h.value} value={h.value}>
              {h.label}
            </option>
          ))}
        </select>
        <span className="error">{inputs.holdError}</span>
      </label>
      <button type="submit" className="btn btn-primary">
        Split it
      </button>
    </form>
  )
}
