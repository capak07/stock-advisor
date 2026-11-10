'use server'

import { revalidatePath } from 'next/cache'
import { parseSettings } from '@/lib/settings-form'
import { createClient } from '@/lib/supabase/server'
import { formFields, type FormState } from '@/lib/trade-form'

/** The owner may update the one settings row, never add or remove it (spec §8). */
export async function saveSettings(_: FormState, form: FormData): Promise<FormState> {
  const parsed = parseSettings(formFields(form))
  if ('errors' in parsed) return { errors: parsed.errors, at: Date.now() }
  const supabase = await createClient()
  const { error, count } = await supabase
    .from('settings')
    .update({ ...parsed.input, updated_at: new Date().toISOString() }, { count: 'exact' })
    .eq('id', 1)
  if (error) return { message: `Settings weren't saved: ${error.message}`, at: Date.now() }
  if (count === 0) return { message: "Settings weren't saved: only the owner can change them.", at: Date.now() }
  revalidatePath('/settings')
  revalidatePath('/')
  revalidatePath('/daytrade')
  return { ok: true, message: 'Settings saved: they apply from the next run', at: Date.now() }
}
