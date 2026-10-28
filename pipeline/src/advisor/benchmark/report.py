"""Markdown and JSON for a stored benchmark run."""
from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping
from pathlib import Path

_ABLATION_ORDER = ("baseline", "factors", "garch", "factors+garch", "full+policy")

SURVIVORSHIP = (
    "Survivorship: the stock universes are today's listings — Yahoo has no delisted tickers "
    "and SEC's ticker map is current-only — so every result here is optimistic by an unknown amount."
)


def _missing(value: object) -> bool:
    return value is None or (isinstance(value, float) and not math.isfinite(value))


def _fmt(value: object, spec: str) -> str:
    return "—" if _missing(value) else format(value, spec)


def _pct(value: object) -> str:
    return "—" if _missing(value) else f"{value:.0%}"


def _net(value: object) -> str:
    return "—" if _missing(value) else f"{value:.2f}%"


def _worst(by_horizon: Mapping) -> float | None:
    nums = [row["calibration_pts"] for row in by_horizon.values() if not _missing(row.get("calibration_pts"))]
    return max(nums) if nums else None


def _fold_order(keys: Iterable) -> list:
    def sort_key(k):
        if str(k) == "pooled":
            return (1, 0)
        try:
            return (0, int(k))
        except (TypeError, ValueError):
            return (2, str(k))

    return sorted(keys, key=sort_key)


def _choice_line(market: Mapping) -> str:
    chosen = market["chosen"]
    accepted = market["accepted"]
    if accepted.get("changed"):
        return f"**Chosen:** {chosen} — {accepted['reason']}"
    return f"**Chosen:** {chosen} — unchanged"


def _decision(name: str, market: Mapping) -> str:
    if name == "baseline":
        return "reference"
    decision = (market.get("decisions") or {}).get(name)
    if not decision:
        return "—"
    if decision.get("accepted"):
        return "accepted"
    reasons = decision.get("reasons") or []
    return f"rejected: {reasons[0]}" if reasons else "rejected"


def _ablation_row(name: str, variant: Mapping, market: Mapping) -> str:
    if variant.get("status") != "run":
        return f"| {name} | arrives with {variant.get('plan', '')} | — | — | — | — |"
    if "summary" not in variant:  # the policy row: no model scores of its own
        return f"| {name} | run | — | — | — | {_decision(name, market)} |"
    summary = variant["summary"]["pooled"]
    return (
        f"| {name} | run | {_fmt(summary['rank_ic'], '.3f')} | {_fmt(summary['pinball'], '.5f')} "
        f"| {_fmt(_worst(variant['model']['pooled']), '.1f')} | {_decision(name, market)} |"
    )


def _mean_coverage(by_horizon: Mapping) -> object:
    nums = [row["coverage_10_90"] for row in by_horizon.values() if not _missing(row.get("coverage_10_90"))]
    return sum(nums) / len(nums) if nums else None


def _outer_folds_table(name: str, variant: Mapping) -> list[str]:
    model, summary = variant["model"], variant["summary"]
    lines = [
        f"### Outer folds: {name}",
        "",
        "| Fold | Rank IC | Pinball | Worst calibration | Coverage q10–q90 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for fold in _fold_order(summary):
        s, by_h = summary[fold], model.get(fold, {})
        cal = "— (no earlier predictions)" if str(fold) == "0" else _fmt(_worst(by_h), ".1f")
        lines.append(
            f"| {fold} | {_fmt(s['rank_ic'], '.3f')} | {_fmt(s['pinball'], '.5f')} "
            f"| {cal} | {_pct(_mean_coverage(by_h))} |"
        )
    return lines


def _policy_table(variant: Mapping) -> list[str]:
    policy = variant.get("policy") or {}
    lines = [
        "### Default policy (folds 1–3)",
        "",
        "| Fold | Trades | Trades/month | Net per trade | Hit rate | Claimed P vs beat rate |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for fold in _fold_order(k for k in policy if str(k) != "0"):
        row = policy[fold]
        claimed = (
            "—"
            if _missing(row.get("mean_p")) or _missing(row.get("beat_rate"))
            else f"{_pct(row['mean_p'])} vs {_pct(row['beat_rate'])}"
        )
        trades = "—" if _missing(row.get("trades")) else str(int(row["trades"]))
        lines.append(
            f"| {fold} | {trades} | {_fmt(row.get('trades_per_month'), '.1f')} "
            f"| {_net(row.get('mean_net_pct'))} | {_pct(row.get('hit_rate_net'))} | {claimed} |"
        )
    return lines


def _ordered(variants: Mapping) -> list[tuple[str, Mapping]]:
    names = [name for name in _ABLATION_ORDER if name in variants]
    names += [name for name in variants if name not in names]
    return [(name, variants[name]) for name in names]


def _book(value: object) -> Mapping:
    if isinstance(value, Mapping) and isinstance(value.get("pooled"), Mapping):
        return value["pooled"]
    return value if isinstance(value, Mapping) else {}


def _policy_bits(raw: Mapping) -> str:
    horizons = raw.get("horizons")
    days = "all" if horizons is None else ", ".join(str(day) for day in horizons)
    return (
        f"p_buy {raw['p_buy']:.2f}, p_sell {raw['p_sell']:.2f}, swing_atr {raw['swing_atr']}, "
        f"position_atr {raw['position_atr']}, trail_atr {raw['trail_atr']}, rule {raw['rule']}, "
        f"horizons {days}"
    )


def _book_row(label: str, book: Mapping) -> str:
    claimed = (
        "—"
        if _missing(book.get("mean_p")) or _missing(book.get("beat_rate"))
        else f"{_pct(book['mean_p'])} vs {_pct(book['beat_rate'])}"
    )
    trades = "—" if _missing(book.get("trades")) else str(int(book["trades"]))
    return (
        f"| {label} | {trades} | {_fmt(book.get('trades_per_month'), '.1f')} "
        f"| {_net(book.get('mean_net_pct'))} | {_pct(book.get('hit_rate_net'))} "
        f"| {_fmt(book.get('sharpe'), '.2f')} | {_pct(book.get('max_drawdown'))} | {claimed} |"
    )


def _tuned_policy(policy: Mapping, market: Mapping) -> list[str]:
    lines = [
        "### Policy (folds 1–3)",
        "",
        "| Book | Trades | Trades/month | Net per trade | Hit rate | Net Sharpe | Max drawdown | Claimed P vs beat rate |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
        _book_row("today's rules", _book(policy.get("default"))),
        _book_row("tuned", _book(policy.get("candidate"))),
        "",
    ]
    fold_reasons = policy.get("per_fold_reasons") or []
    for fold, raw in enumerate(policy.get("per_fold") or [], start=1):
        text = f"Fold {fold}: {_policy_bits(raw)}" if isinstance(raw, Mapping) else f"Fold {fold}: no policy"
        why = fold_reasons[fold - 1] if fold - 1 < len(fold_reasons) else None
        lines.append(f"{text} — {why}" if why else text)
    final = policy.get("final")
    if isinstance(final, Mapping):
        lines.append(f"Final policy: {_policy_bits(final)}")
    elif policy.get("final_reason"):
        lines.append(f"No final policy: {policy['final_reason']}")
    else:
        lines.append("No final policy")
    lines.append(f"Decision: {_decision('full+policy', market)}")
    return lines


def _how(constants: Mapping) -> list[str]:
    pinball_pct = constants["pinball_tolerance"] * 100
    n, folds = constants["min_folds_improved"], constants["outer_folds"]
    cal = constants["max_calibration_pts"]
    return [
        "## How decisions are made",
        "",
        "- pooled rank IC must improve on the reference",
        f"- pinball loss may be no worse than {pinball_pct:g}%",
        f"- rank IC must improve in at least {n} of {folds} outer folds",
        f"- calibration must be within {cal:g} points at every usable horizon",
        "- outer fold 0 has no calibration or policy score",
        "- a candidate must also beat the currently accepted configuration",
    ]


def render_markdown(report: Mapping) -> str:
    day = str(report["started_at"])[:10]
    sha = report.get("git_sha") or "—"
    lines = [
        f"# Benchmark report — {day} ({sha})",
        "",
        f"> {SURVIVORSHIP}",
        "",
    ]
    for market_name, market in report["markets"].items():
        lines += [f"## {market_name}", ""]
        if "error" in market:
            lines += [f"Failed: {market['error']}", ""]
            continue
        lines += [_choice_line(market), "", "### Ablations", ""]
        lines += [
            "| Variant | Status | Rank IC (pooled) | Pinball (pooled) | Worst calibration | Decision |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for name, variant in _ordered(market["variants"]):
            lines.append(_ablation_row(name, variant, market))
        lines.append("")
        for name, variant in _ordered(market["variants"]):
            if variant.get("status") != "run":
                continue
            if "summary" not in variant:  # the policy row has books, not model scores
                stored = variant.get("policy")
                if isinstance(stored, Mapping):
                    lines += _tuned_policy(stored, market)
                    lines.append("")
                continue
            lines += _outer_folds_table(name, variant)
            lines.append("")
            if isinstance(variant.get("policy"), Mapping):
                lines += _policy_table(variant)
                lines.append("")
    lines += _how(report["constants"])
    lines.append("")
    return "\n".join(lines)


def write_reports(report: Mapping, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "benchmark-report.json").write_text(json.dumps(report, indent=2) + "\n")
    (out / "benchmark-report.md").write_text(render_markdown(report))
