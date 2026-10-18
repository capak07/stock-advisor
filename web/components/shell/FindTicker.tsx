'use client'

import { Search } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useState, type FormEvent } from 'react'
import { isValidSymbol, normalizeSymbol } from '@/lib/symbols'

/** Go to any symbol's Ticker page; the page works out whether it's a stock or a coin. */
export function FindTicker({ onGo }: { onGo?: () => void }) {
  const router = useRouter()
  const [value, setValue] = useState('')
  const [error, setError] = useState<string | null>(null)

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const symbol = normalizeSymbol(value)
    if (!symbol) return
    if (!isValidSymbol(symbol, 'stock') && !isValidSymbol(symbol, 'crypto')) {
      setError('Try a symbol like NVDA, SHOP.TO or BTC.')
      return
    }
    setError(null)
    setValue('')
    onGo?.()
    router.push(`/ticker/${encodeURIComponent(symbol)}`)
  }

  return (
    <form role="search" className={`field ${error ? 'invalid' : ''}`} onSubmit={submit} noValidate>
      <label className="find">
        <span className="sr-only">Find a symbol</span>
        <Search aria-hidden="true" />
        <input
          type="search"
          className="input num-input"
          placeholder="Find a symbol"
          autoCapitalize="characters"
          enterKeyHint="go"
          value={value}
          onChange={(e) => {
            setValue(e.target.value)
            setError(null)
          }}
        />
      </label>
      <span className="error">{error}</span>
    </form>
  )
}
