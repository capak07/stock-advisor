'use client'

import { useState } from 'react'
import type { FormState } from '@/lib/trade-form'

/**
 * A field's error from the last answer, until the owner edits the field. Every field is
 * controlled: React resets uncontrolled fields after each action, which would wipe what the
 * owner typed whenever the server answers with an error.
 *
 * A field counts as edited when it was edited while the current answer was showing. That compares
 * answer objects, not times: `useActionState` gives a new object for every answer, and the
 * server's clock and the device's may differ.
 */
export function useFieldErrors(state: FormState) {
  const [edited, setEdited] = useState<Record<string, FormState>>({})
  const editedSince = (name: string) => edited[name] === state
  const error = (name: string) => {
    const message = state.errors?.[name]
    return message && !editedSince(name) ? message : undefined
  }
  const touch = (name: string) => setEdited((e) => ({ ...e, [name]: state }))
  return { error, touch, editedSince }
}
