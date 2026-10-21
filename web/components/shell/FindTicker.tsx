'use client'

import { Search } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useState } from 'react'
import { SymbolSearch } from '@/components/SymbolSearch'
import { isValidSymbol, normalizeSymbol } from '@/lib/symbols'
import { tickerHref } from '@/lib/ticker'

/**
 * Go to a Ticker page: pick a stock or coin from the list, or the last row that opens a ticker the
 * lists don't have (an ETF like SPY), and the page works out whether it's a stock or a coin.
 */
export function FindTicker({ onGo }: { onGo?: () => void }) {
  const router = useRouter()
  const [error, setError] = useState<string | null>(null)

  const go = (href: string) => {
    setError(null)
    onGo?.()
    router.push(href)
  }

  const asTicker = (query: string): string | null => {
    const symbol = normalizeSymbol(query)
    return isValidSymbol(symbol, 'stock') || isValidSymbol(symbol, 'crypto') ? symbol : null
  }

  const goToTyped = (query: string) => {
    const symbol = asTicker(query)
    if (!symbol) setError('Try a name or a symbol like NVDA, SHOP.TO or BTC.')
    else go(`/ticker/${encodeURIComponent(symbol)}`)
  }

  return (
    <div role="search" className={`field ${error ? 'invalid' : ''}`}>
      <SymbolSearch
        label="Find a symbol"
        placeholder="Find a symbol"
        icon={<Search aria-hidden="true" />}
        className="find"
        invalid={error !== null}
        emptyText="No stock or coin matches."
        onPick={(item) => go(tickerHref(item.symbol, item.assetType))}
        typedTicker={asTicker}
        onNoMatch={goToTyped}
        onEdit={() => setError(null)}
      />
      <span className="error">{error}</span>
    </div>
  )
}
