import { ChevronDown } from 'lucide-react'
import type { OrderPlan } from '@/lib/orders'

const ORDER_DISCLAIMER = "Order guidance is a rule of thumb for Wealthsimple's order types, not a price forecast."

/**
 * "How to place it": a plan's steps in order, then its cautions in small print. Nothing without steps.
 * `fold` puts it in a `<details>` whose summary is the title (the Invest lines), open or closed to start.
 */
export function OrderGuide({
  plan,
  caption = null,
  fold = null,
}: {
  plan: OrderPlan
  caption?: string | null
  fold?: 'open' | 'closed' | null
}) {
  if (plan.steps.length === 0) return null
  const title = (
    <>
      How to place it{caption && <span className="og-caption"> · {caption}</span>}
    </>
  )
  const body = (
    <>
      {plan.steps.map((s, i) => (
        <span key={i} className="og-step">
          {s.text}
        </span>
      ))}
      {plan.notes.map((n) => (
        <span key={n} className="sub og-note">
          {n}
        </span>
      ))}
    </>
  )
  if (fold !== null) {
    return (
      <details className="order-guide og-fold" open={fold === 'open'}>
        <summary>
          <span>{title}</span>
          <ChevronDown aria-hidden="true" />
        </summary>
        <div className="og-body">{body}</div>
      </details>
    )
  }
  return (
    <div className="order-guide">
      <span className="label">{title}</span>
      {body}
    </div>
  )
}

/** Once per page that shows order guidance. */
export function OrderDisclaimer({ style }: { style?: React.CSSProperties }) {
  return (
    <p className="sub order-disclaimer" style={{ margin: 0, ...style }}>
      {ORDER_DISCLAIMER}
    </p>
  )
}
