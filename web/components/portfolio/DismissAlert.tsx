'use client'

import { useTransition } from 'react'
import { dismissAlert } from '@/app/(app)/ticker/[symbol]/alerts'
import { useToast } from '@/components/Toast'

/** Dismiss a hit alert from the My Portfolio feed. */
export function DismissAlert({ id }: { id: number }) {
  const toast = useToast()
  const [pending, startTransition] = useTransition()
  return (
    <button
      type="button"
      className="btn btn-sm btn-secondary"
      disabled={pending}
      onClick={() =>
        startTransition(async () => {
          const result = await dismissAlert(id)
          if (result.message) toast(result.message)
        })
      }
    >
      Dismiss
    </button>
  )
}
