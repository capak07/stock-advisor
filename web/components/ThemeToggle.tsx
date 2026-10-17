'use client'

import { Moon, Sun } from 'lucide-react'
import { useSyncExternalStore } from 'react'
import { applyTheme } from '@/lib/theme'

const subscribe = (onChange: () => void) => {
  const observer = new MutationObserver(onChange)
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
  return () => observer.disconnect()
}
const isDark = () => document.documentElement.classList.contains('dark')

/** Follows the page's "dark" class, which the head script set before React ran. */
export function useDarkMode(): boolean {
  return useSyncExternalStore(subscribe, isDark, () => false)
}

export function ThemeToggle({ className = '' }: { className?: string }) {
  const dark = useDarkMode()
  return (
    <button
      type="button"
      className={`icon-btn ${className}`}
      aria-label="Switch between light and dark"
      onClick={() => applyTheme(dark ? 'light' : 'dark')}
    >
      {dark ? <Sun /> : <Moon />}
    </button>
  )
}
