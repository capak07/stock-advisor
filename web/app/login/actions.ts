'use server'

import { redirect } from 'next/navigation'
import { z } from 'zod'
import { createClient } from '@/lib/supabase/server'

export interface SignInState {
  email: string
  error?: string
  missing?: ('email' | 'password')[]
}

const credentials = z.object({ email: z.string().trim().min(1), password: z.string().min(1) })

/** Email and password sign-in (spec §9). Sign-ups are off in Supabase, so only the owner exists. */
export async function signIn(_: SignInState, form: FormData): Promise<SignInState> {
  const email = String(form.get('email') ?? '')
  const parsed = credentials.safeParse({ email, password: form.get('password') ?? '' })
  if (!parsed.success) {
    const missing = parsed.error.issues.map((issue) => issue.path[0] as 'email' | 'password')
    return { email, missing }
  }
  const supabase = await createClient()
  const { error } = await supabase.auth.signInWithPassword(parsed.data)
  if (error) return { email, error: "That email and password don't match." }
  redirect('/')
}
