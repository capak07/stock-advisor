import 'server-only'
import { createServerClient } from '@supabase/ssr'
import { cookies } from 'next/headers'

/**
 * Supabase settings. The dashboard only talks to Supabase from the server, so neither value is
 * shipped to the browser. The publishable key carries no rights of its own: row-level security
 * gives the signed-in owner, and nobody else, access to the data (spec §8).
 */
export function supabaseEnv(): { url: string; key: string } {
  const url = process.env.SUPABASE_URL
  const key = process.env.SUPABASE_PUBLISHABLE_KEY
  if (!url || !key) throw new Error('Set SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY (see web/README.md).')
  return { url, key }
}

/** A client for one server render or server action, signed in as the visitor's session. */
export async function createClient() {
  const cookieStore = await cookies()
  const { url, key } = supabaseEnv()
  return createServerClient(url, key, {
    cookies: {
      getAll: () => cookieStore.getAll(),
      setAll: (cookiesToSet) => {
        try {
          for (const { name, value, options } of cookiesToSet) cookieStore.set(name, value, options)
        } catch {
          // A server component can't set cookies; the proxy keeps the session fresh instead.
        }
      },
    },
  })
}

export type Supabase = Awaited<ReturnType<typeof createClient>>
