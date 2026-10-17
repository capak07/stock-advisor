import { execSync } from 'node:child_process'
import { mkdirSync } from 'node:fs'
import { join } from 'node:path'

/** The local Supabase stack (`npm run db:start`, see web/README.md). */
export interface Stack {
  API_URL: string
  DB_URL: string
  PUBLISHABLE_KEY: string
  SECRET_KEY: string
}

/**
 * The stack's URLs and keys, from `supabase status`. Playwright loads its config in the main
 * process and in each worker; the main process asks once and the workers inherit the answer.
 */
export function localStack(): Stack {
  if (!process.env.E2E_STACK) {
    let out: string
    try {
      out = execSync('npx supabase status -o json --workdir ..', {
        cwd: join(__dirname, '..'),
        encoding: 'utf8',
        stdio: ['ignore', 'pipe', 'ignore'],
      })
    } catch {
      throw new Error('The local Supabase stack is not running. Start it with `npm run db:start` (see web/README.md).')
    }
    process.env.E2E_STACK = out.slice(out.indexOf('{'), out.lastIndexOf('}') + 1)
  }
  return JSON.parse(process.env.E2E_STACK) as Stack
}

/** Test accounts on the local stack only. */
export const OWNER = { email: 'owner@example.com', password: 'local-owner-password' }
export const VISITOR = { email: 'visitor@example.com', password: 'local-visitor-password' }

const AUTH_DIR = join(__dirname, '.auth')
mkdirSync(AUTH_DIR, { recursive: true })
export const OWNER_STATE = join(AUTH_DIR, 'owner.json')
