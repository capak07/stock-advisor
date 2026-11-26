import 'server-only'
import { cookies } from 'next/headers'
import { E2E_NOW_COOKIE, clockNow } from '../clock'

/** The time the page renders at: the real time, or under the browser tests (E2E_CLOCK=1) the time a
 * test pinned with the e2e-now cookie. */
export async function serverNow(): Promise<string> {
  const enabled = process.env.E2E_CLOCK === '1'
  const pinned = enabled ? (await cookies()).get(E2E_NOW_COOKIE)?.value : undefined
  return clockNow(new Date(), pinned, enabled)
}
