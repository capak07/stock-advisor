import 'server-only'
import { redirect } from 'next/navigation'
import { cache } from 'react'
import { createClient, type Supabase } from './supabase/server'

/**
 * The visitor's session, once per request: signed out goes to /login. `owner` is whether the
 * visitor is the owner named in `app_config`, the only one row-level security shows data to.
 */
export const session = cache(async (): Promise<{ supabase: Supabase; owner: boolean }> => {
  const supabase = await createClient()
  const { data } = await supabase.auth.getClaims()
  if (!data?.claims) redirect('/login')
  const { data: owner, error } = await supabase.rpc('is_owner')
  if (error) throw new Error(error.message)
  return { supabase, owner: owner === true }
})

/**
 * For pages: the owner's client, or null. Next renders a page alongside its layout, so a page
 * must not load data when the layout is showing someone else the not-the-owner notice.
 */
export async function ownerClient(): Promise<Supabase | null> {
  const { supabase, owner } = await session()
  return owner ? supabase : null
}
