'use client'

import { CircleCheck } from 'lucide-react'
import { createContext, useCallback, useContext, useRef, useState } from 'react'

const ToastContext = createContext<(message: string) => void>(() => {})

/** One toast at a time, top right, for 4 seconds (ledger.css `.toast`). */
export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [message, setMessage] = useState('')
  const [shown, setShown] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined)
  const show = useCallback((text: string) => {
    setMessage(text)
    setShown(true)
    clearTimeout(timer.current)
    timer.current = setTimeout(() => setShown(false), 4000)
  }, [])
  return (
    <ToastContext.Provider value={show}>
      {children}
      <div className={`toast ${shown ? 'show' : ''}`} role="status">
        <CircleCheck />
        <span>{message}</span>
      </div>
    </ToastContext.Provider>
  )
}

export const useToast = () => useContext(ToastContext)
