import { LogOut } from 'lucide-react'
import type { Metadata } from 'next'
import { CostsForm, ThemeTabs } from '@/components/settings/SettingsForms'
import { ownerClient } from '@/lib/auth'
import { loadSettings } from '@/lib/data/settings'
import { longDay } from '@/lib/dates'
import { signOut } from '../actions'

export const metadata: Metadata = { title: 'Settings' }

/** Settings (spec §9): the USD conversion fee, the crypto spread and the TFSA guideline. */
export default async function SettingsPage() {
  const supabase = await ownerClient()
  if (!supabase) return null // the layout is showing the not-the-owner notice
  const settings = await loadSettings(supabase)
  const changed = longDay(
    new Intl.DateTimeFormat('en-CA', { timeZone: 'America/Toronto' }).format(new Date(settings.updated_at)),
  )
  return (
    <main className="page">
      <div className="enter">
        <h1>Settings</h1>
        <p className="sub">Costs and guidelines the recommendations use. Changes apply from the next run.</p>
      </div>
      <div className="settings">
        <CostsForm
          changed={changed}
          initial={{
            usd_fx_fee_pct: String(settings.usd_fx_fee_pct),
            crypto_fee_pct: String(settings.crypto_fee_pct),
            tfsa_round_trips_warn: String(settings.tfsa_round_trips_warn),
            tfsa_short_hold_share_warn: String(Math.round(settings.tfsa_short_hold_share_warn * 100)),
          }}
        />
        <section className="card card-pad enter">
          <h2 style={{ marginBottom: 4 }}>Appearance</h2>
          <div className="setting" style={{ borderBottom: 0 }}>
            <span>
              <strong>Theme</strong>
              <p>Saved on this device only.</p>
            </span>
            <ThemeTabs />
          </div>
        </section>
        <section className="card card-pad enter">
          <h2 style={{ marginBottom: 4 }}>Account</h2>
          <div className="setting" style={{ borderBottom: 0 }}>
            <span>
              <strong>Signed in as the owner</strong>
              <p>This dashboard has one account. Sign-ups are turned off.</p>
            </span>
            <form action={signOut}>
              <button type="submit" className="btn btn-secondary">
                <LogOut />
                Sign out
              </button>
            </form>
          </div>
        </section>
      </div>
    </main>
  )
}
