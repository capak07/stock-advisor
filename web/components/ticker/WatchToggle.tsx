'use client'

import { Check, Eye } from 'lucide-react'
import { useTransition } from 'react'
import { addWatch, removeWatch } from '@/app/(app)/watchlist/actions'
import { useToast } from '@/components/Toast'
import type { AssetType } from '@/lib/portfolio/types'

/** Watch or stop watching the asset on its own page, through the watchlist's actions. */
export function WatchToggle({ symbol, assetType, watched }: { symbol: string; assetType: AssetType; watched: boolean }) {
  const toast = useToast()
  const [pending, startTransition] = useTransition()

  const toggle = () =>
    startTransition(async () => {
      let message: string | undefined
      if (watched) {
        message = (await removeWatch(symbol, assetType)).message
      } else {
        const result = await addWatch(symbol, assetType)
        message = result.message ?? result.errors?.symbol
      }
      if (message) toast(message)
    })

  return (
    <button
      type="button"
      className={`btn btn-sm ${watched ? 'btn-secondary' : 'btn-primary'}`}
      aria-pressed={watched}
      disabled={pending}
      onClick={toggle}
    >
      {watched ? <Check /> : <Eye />}
      {watched ? 'Watching' : 'Watch'}
    </button>
  )
}
