'use client'

import { RefreshCw } from 'lucide-react'
import { useTransition } from 'react'
import { refreshQuotes } from '@/app/(app)/quotes'
import { useToast } from '../Toast'

const TIME = new Intl.DateTimeFormat('en-CA', { hour: 'numeric', minute: '2-digit', timeZone: 'America/Toronto' })

/**
 * Refresh: fetches live prices for everything held or watched (lib/quotes.ts). After one, the pill
 * says when, so a value can be told from the last run's.
 */
export function RefreshPrices({ liveAt }: { liveAt: string | null }) {
  const toast = useToast()
  const [pending, start] = useTransition()
  const refresh = () =>
    start(async () => {
      const result = await refreshQuotes()
      toast(result.message)
    })
  return (
    <>
      {liveAt && (
        <span className="pill hide-sm" id="live-prices" title="Values use these live prices; forecasts and actions are from the last run">
          <span className="dot ok" />
          Live prices {TIME.format(new Date(liveAt))}
        </span>
      )}
      <button
        type="button"
        className={`icon-btn ${pending ? 'spinning' : ''}`}
        aria-label={pending ? 'Refreshing prices' : 'Refresh prices'}
        title="Refresh prices"
        disabled={pending}
        onClick={refresh}
      >
        <RefreshCw />
      </button>
    </>
  )
}
