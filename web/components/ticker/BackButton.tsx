'use client'

import { ChevronLeft } from 'lucide-react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'

/** The Navigation API's flag, where the browser has it (Chromium: Edge, Chrome, the Android WebView). */
type WithNavigation = Window & { navigation?: { canGoBack?: boolean } }

/**
 * Whether the page before this one is one of the app's own: the Navigation API's history holds only
 * this origin's entries; without it, a same-origin referrer with history behind it.
 */
function cameFromApp(): boolean {
  const canGoBack = (window as WithNavigation).navigation?.canGoBack
  if (typeof canGoBack === 'boolean') return canGoBack
  try {
    return window.history.length > 1 && document.referrer !== '' && new URL(document.referrer).origin === window.location.origin
  } catch {
    return false
  }
}

/**
 * The stock page's back chevron: back to the page the owner came from (Today, the Watchlist, Search…)
 * when it is one of the app's; otherwise, opened from outside or in a new tab, to My Portfolio. A link
 * to /portfolio underneath, so it works before the script loads and with a modifier key.
 */
export function BackButton() {
  const router = useRouter()
  return (
    <Link
      href="/portfolio"
      className="t-back"
      aria-label="Back"
      onNavigate={(e) => {
        if (!cameFromApp()) return
        e.preventDefault()
        router.back()
      }}
    >
      <ChevronLeft />
    </Link>
  )
}
