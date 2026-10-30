'use client'

import { useEffect } from 'react'

type Bridge = { isNativePlatform?: () => boolean }

/** Status bar and the Android back button. A normal browser has no Capacitor bridge, so this does nothing there. */
export function NativeShell() {
  useEffect(() => {
    const bridge = (window as Window & { Capacitor?: Bridge }).Capacitor
    if (!bridge?.isNativePlatform?.()) return
    let remove = () => {}
    let gone = false
    void (async () => {
      const { StatusBar, Style } = await import('@capacitor/status-bar')
      const { App } = await import('@capacitor/app')
      if (gone) return
      const dark = document.documentElement.classList.contains('dark')
      await StatusBar.setOverlaysWebView({ overlay: false })
      await StatusBar.setStyle({ style: dark ? Style.Dark : Style.Light })
      const handle = await App.addListener('backButton', ({ canGoBack }) => {
        if (canGoBack) window.history.back()
        else void App.exitApp()
      })
      if (gone) void handle.remove()
      else remove = () => void handle.remove()
    })()
    return () => {
      gone = true
      remove()
    }
  }, [])
  return null
}
