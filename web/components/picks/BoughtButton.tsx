'use client'

import { createContext, useCallback, useContext, useState } from 'react'
import { Drawer } from '@/components/Drawer'
import { BuyForm, type BuyInitial } from '@/components/portfolio/TradeForms'
import { useToast } from '@/components/Toast'
import type { FxRate } from '@/lib/portfolio/lookup'

const OpenBuy = createContext<((initial: BuyInitial) => void) | null>(null)

/** One buy drawer for the page's "I bought this" buttons, with the rates the form needs. */
export function PickBuyDrawer({ rates, today, children }: { rates: FxRate[]; today: string; children: React.ReactNode }) {
  const toast = useToast()
  const [initial, setInitial] = useState<BuyInitial | null>(null)
  const [open, setOpen] = useState(false)
  // Each opening starts a fresh form.
  const [round, setRound] = useState(0)
  const show = useCallback((next: BuyInitial) => {
    setInitial(next)
    setRound((n) => n + 1)
    setOpen(true)
  }, [])
  const close = useCallback(() => setOpen(false), [])
  const done = useCallback(
    (message: string) => {
      setOpen(false)
      toast(message)
    },
    [toast],
  )
  return (
    <OpenBuy.Provider value={show}>
      {children}
      <Drawer id="buy-drawer" title="Add a buy" open={open} onClose={close}>
        {initial && <BuyForm key={round} rates={rates} today={today} onDone={done} onCancel={close} initial={initial} />}
      </Drawer>
    </OpenBuy.Provider>
  )
}

/** Opens the buy drawer pre-filled from the pick: its symbol, the TFSA, and its entry price. */
export function BoughtButton({ pick }: { pick: { id: number; symbol: string; entry: number } }) {
  const open = useContext(OpenBuy)
  if (!open) return null
  return (
    <button
      type="button"
      className="btn btn-primary btn-sm"
      onClick={() => open({ symbol: pick.symbol, account: 'tfsa', price: String(pick.entry), pickId: pick.id })}
    >
      I bought this
    </button>
  )
}
