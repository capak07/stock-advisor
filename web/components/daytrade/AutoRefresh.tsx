'use client'

import { useRouter } from 'next/navigation'
import { useEffect } from 'react'

/** Re-renders the page from the server every `every` ms while the tab is visible, and as soon as it
 * becomes visible again. Mounted only while the day is live, so it stops when the day ends. */
export function AutoRefresh({ every = 60_000 }: { every?: number }) {
  const router = useRouter()
  useEffect(() => {
    const visible = () => document.visibilityState === 'visible'
    const id = window.setInterval(() => {
      if (visible()) router.refresh()
    }, every)
    const onShow = () => {
      if (visible()) router.refresh()
    }
    document.addEventListener('visibilitychange', onShow)
    return () => {
      window.clearInterval(id)
      document.removeEventListener('visibilitychange', onShow)
    }
  }, [router, every])
  return null
}
