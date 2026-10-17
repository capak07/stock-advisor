import type { Metadata } from 'next'
import { ThemeToggle } from '@/components/ThemeToggle'
import { DISCLAIMER } from '@/lib/copy'
import { LoginForm } from './LoginForm'

export const metadata: Metadata = { title: 'Sign in' }

export default function LoginPage() {
  return (
    <>
      <ThemeToggle className="theme-corner" />
      <main className="login-wrap">
        <div className="login enter">
          <div className="brand" style={{ justifyContent: 'center', padding: 0 }}>
            <span className="brand-mark" aria-hidden="true">
              A
            </span>
            ADVISOR
          </div>
          <LoginForm />
          <p className="sub" style={{ margin: 0, textAlign: 'center', fontSize: 12 }}>
            {DISCLAIMER}
          </p>
        </div>
      </main>
    </>
  )
}
