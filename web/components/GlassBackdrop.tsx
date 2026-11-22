'use client'

import { useEffect, useRef } from 'react'
import { supportsLiquidGlass } from '@/lib/glass'

/** navigator.userAgentData is Chromium-only and not in every TypeScript DOM lib. */
type UserAgentData = { brands?: readonly { brand: string }[] }

/**
 * The aurora behind every page and the #liquid filter the bars refract through (glass.css).
 * Marks <html> "liquid" in Chrome-based browsers and rests the aurora while the page is hidden.
 */
export function GlassBackdrop() {
  const aurora = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const nav = navigator as Navigator & { userAgentData?: UserAgentData }
    document.documentElement.classList.toggle('liquid', supportsLiquidGlass(nav.userAgentData?.brands, nav.userAgent))
    const rest = () => aurora.current?.classList.toggle('paused', document.hidden)
    rest()
    document.addEventListener('visibilitychange', rest)
    return () => document.removeEventListener('visibilitychange', rest)
  }, [])

  return (
    <>
      <div ref={aurora} className="aurora" aria-hidden="true" />
      <svg width="0" height="0" style={{ position: 'absolute' }} aria-hidden="true">
        <filter id="liquid" x="0" y="0" width="100%" height="100%" colorInterpolationFilters="sRGB">
          <feTurbulence type="fractalNoise" baseFrequency="0.008 0.012" numOctaves={2} seed={7} result="noise" />
          <feGaussianBlur in="noise" stdDeviation={2} result="soft" />
          <feDisplacementMap in="SourceGraphic" in2="soft" scale={38} xChannelSelector="R" yChannelSelector="G" />
        </filter>
      </svg>
    </>
  )
}
