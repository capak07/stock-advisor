'use client'

import { useEffect } from 'react'
import { deviceStorage, pushRecent, readRecent, writeRecent } from '@/lib/recent'

/** Puts this stock or coin first in the phone Search sheet's recent list (lib/recent.ts); renders nothing. */
export function RememberVisit({ symbol }: { symbol: string }) {
  useEffect(() => {
    const storage = deviceStorage()
    writeRecent(storage, pushRecent(readRecent(storage), symbol))
  }, [symbol])
  return null
}
