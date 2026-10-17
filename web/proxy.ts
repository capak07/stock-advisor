import { createServerClient } from '@supabase/ssr'
import { NextResponse, type NextRequest } from 'next/server'

/**
 * Runs before every page and server action: refreshes the Supabase session cookie, sends signed-out
 * visitors to /login, and signed-in ones away from it. Pages still check for the owner; this is
 * only the first gate (row-level security is the last).
 */
export async function proxy(request: NextRequest) {
  const url = process.env.SUPABASE_URL
  const key = process.env.SUPABASE_PUBLISHABLE_KEY
  if (!url || !key) throw new Error('Set SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY (see web/README.md).')

  let response = NextResponse.next({ request })
  const supabase = createServerClient(url, key, {
    cookies: {
      getAll: () => request.cookies.getAll(),
      setAll: (cookiesToSet, headers) => {
        for (const { name, value } of cookiesToSet) request.cookies.set(name, value)
        response = NextResponse.next({ request })
        for (const { name, value, options } of cookiesToSet) response.cookies.set(name, value, options)
        for (const [name, value] of Object.entries(headers ?? {})) response.headers.set(name, value)
      },
    },
  })
  const { data } = await supabase.auth.getClaims()
  const signedIn = Boolean(data?.claims)
  const onLogin = request.nextUrl.pathname === '/login'

  if (signedIn === onLogin) {
    const to = request.nextUrl.clone()
    to.pathname = signedIn ? '/' : '/login'
    to.search = ''
    const redirect = NextResponse.redirect(to)
    for (const cookie of response.cookies.getAll()) redirect.cookies.set(cookie)
    return redirect
  }
  return response
}

export const config = {
  // Everything but Next's static files and the icon.
  matcher: ['/((?!_next/static|_next/image|icon.svg|favicon.ico).*)'],
}
