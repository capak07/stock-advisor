import type { OrderPlan } from '@/lib/orders'

const ORDER_DISCLAIMER = "Order guidance is a rule of thumb for Wealthsimple's order types, not a price forecast."

/** "How to place it": a plan's steps in order, then its cautions in small print. Nothing without steps. */
export function OrderGuide({ plan, caption = null }: { plan: OrderPlan; caption?: string | null }) {
  if (plan.steps.length === 0) return null
  return (
    <div className="order-guide">
      <span className="label">
        How to place it{caption && <span className="og-caption"> · {caption}</span>}
      </span>
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
