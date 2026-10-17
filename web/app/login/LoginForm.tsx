'use client'

import { TriangleAlert } from 'lucide-react'
import { useActionState } from 'react'
import { signIn, type SignInState } from './actions'

export function LoginForm() {
  const [state, action, pending] = useActionState<SignInState, FormData>(signIn, { email: '' })
  const missing = new Set(state.missing ?? [])
  return (
    <form className="card" action={action} noValidate>
      <div>
        <h1>Sign in</h1>
        <p className="sub" style={{ margin: '4px 0 0' }}>
          Your portfolio, picks and track record.
        </p>
      </div>
      {state.error && (
        <div className="banner danger" role="alert">
          <TriangleAlert />
          <div>{state.error}</div>
        </div>
      )}
      <label className={`field ${missing.has('email') ? 'invalid' : ''}`}>
        <span>Email</span>
        <input
          className="input"
          type="email"
          name="email"
          autoComplete="username"
          placeholder="you@example.com"
          defaultValue={state.email}
          required
        />
        <span className="error">Enter your email.</span>
      </label>
      <label className={`field ${missing.has('password') ? 'invalid' : ''}`}>
        <span>Password</span>
        <input className="input" type="password" name="password" autoComplete="current-password" required />
        <span className="error">Enter your password.</span>
      </label>
      <button type="submit" className="btn btn-primary" style={{ width: '100%', padding: '11px 14px' }} disabled={pending}>
        {pending ? 'Signing in…' : 'Sign in'}
      </button>
      <p className="sub" style={{ margin: 0, textAlign: 'center' }}>
        One owner, no sign-ups.
      </p>
    </form>
  )
}
