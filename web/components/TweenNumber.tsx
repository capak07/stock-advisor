'use client'

import { useEffect, useRef, useState } from 'react'
import { ease } from '@/lib/chart'

/** A number that counts to its new value over 250 ms (the mockups' `tweenNumber`). */
export function TweenNumber({
  value,
  format,
  className,
}: {
  value: number
  format: (value: number) => string
  className?: string
}) {
  const [shown, setShown] = useState(value)
  const from = useRef(value)

  useEffect(() => {
    const start = performance.now()
    const begin = from.current
    from.current = value
    if (begin === value) return
    const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches
    let frame = requestAnimationFrame(function step(now) {
      const k = reduce ? 1 : Math.min(1, (now - start) / 250)
      setShown(begin + (value - begin) * ease(k))
      if (k < 1) frame = requestAnimationFrame(step)
    })
    return () => cancelAnimationFrame(frame)
  }, [value])

  return <span className={className}>{format(shown)}</span>
}
