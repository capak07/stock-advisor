import type { CapacitorConfig } from '@capacitor/cli'
import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'

/** The deployed dashboard. `mobile/server.url` wins, then CAPACITOR_SERVER_URL. */
function serverUrl(): string | undefined {
  const file = resolve(process.cwd(), 'mobile/server.url')
  const fromFile = existsSync(file)
    ? readFileSync(file, 'utf8')
        .split(/\r?\n/)
        .map((line) => line.trim())
        .find((line) => line.length > 0 && !line.startsWith('#'))
    : undefined
  const url = (fromFile || process.env.CAPACITOR_SERVER_URL || '').trim()
  return url || undefined
}

const url = serverUrl()

const config: CapacitorConfig = {
  appId: 'app.advisor.mobile',
  appName: 'Advisor',
  webDir: 'mobile/www',
  server: url
    ? { url, cleartext: url.startsWith('http://'), androidScheme: 'https' }
    : { androidScheme: 'https' },
  android: { allowMixedContent: false },
}

export default config
