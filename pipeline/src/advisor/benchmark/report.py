"""Markdown and JSON for a stored benchmark run."""
from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping
from pathlib import Path

from advisor.model.groups import DATA_GROUPS

_GROUP_BASE = "garch+ranker+forest"  # `job.GROUP_BASE`: the row each data group row adds one group to
_GROUP_ROWS = {f"{_GROUP_BASE}+{group}": group for group in DATA_GROUPS}
_POLICY_ROW = "full+policy"
_ABLATION_ORDER = (
    "baseline", "ranker", "garch", "factors+garch", "garch+ranker", _GROUP_BASE, "ranker+earnings",
    *_GROUP_ROWS, _POLICY_ROW,
)
# rows a stored report may hold that the benchmark no longer runs (Plan 7b): shown after the known ones
_RETIRED = ("factors", "extras", "ranker+extras", "ranker+extras+bagged")

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
    reason = accepted.get("reason")  # "unchanged", or why it stayed without a comparison (no data)
    kept = reason if isinstance(reason, str) and reason.startswith("unchanged") else "unchanged"
    return f"**Chosen:** {chosen} — {kept}"


def _decision(name: str, market: Mapping) -> str:
    if name == "baseline":
        return "reference"
    if ((market.get("variants") or {}).get(name) or {}).get("status") == "no data":
        return "no data"
    decision = (market.get("decisions") or {}).get(name)
    if not decision:
        return "—"
    if decision.get("accepted"):
        return "accepted"
    reasons = decision.get("reasons") or []
    return f"rejected: {reasons[0]}" if reasons else "rejected"


def _ablation_row(name: str, variant: Mapping, market: Mapping) -> str:
    if variant.get("status") == "no data":  # the build did not write these groups' history
        return f"| {name} | no data: {', '.join(variant.get('groups') or [])} | — | — | — | no data |"
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


def _signed(value: object) -> str:
    return "—" if _missing(value) else f"{value:+.2%}"


def _top_slice_table(name: str, variant: Mapping) -> list[str]:
    """How the top 5% of each day's ranking did, pooled, per horizon (`metrics.top_slice`)."""
    pooled = (variant.get("top_slice") or {}).get("pooled") or {}
    lines = [
        f"### Top 5% by score: {name}",
        "",
        "| Horizon | Days | Top vs all | Top after costs | Bottom vs all |",
        "| --- | --- | --- | --- | --- |",
    ]
    for horizon in sorted(pooled, key=int):  # a stored report's horizons are strings
        row = pooled[horizon]
        days = "—" if _missing(row.get("days")) else str(int(row["days"]))
        lines.append(
            f"| {horizon} | {days} | {_signed(row.get('top_excess'))} | {_signed(row.get('top_net'))} "
            f"| {_signed(row.get('bottom_excess'))} |"
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
    """The known rows in benchmark order, then the rest (a combined or incumbent row in the order they
    ran, then retired rows), and the policy row last."""
    names = [name for name in _ABLATION_ORDER if name in variants and name != _POLICY_ROW]
    names += [name for name in variants if name not in names and name not in _RETIRED and name != _POLICY_ROW]
    names += [name for name in (*_RETIRED, _POLICY_ROW) if name in variants]
    return [(name, variants[name]) for name in names]


def _mean_top_excess(variant: Mapping, horizons: Iterable) -> float | None:
    pooled = (variant.get("top_slice") or {}).get("pooled") or {}
    values = [(pooled.get(h) or {}).get("top_excess") for h in horizons]
    return sum(values) / len(values) if values else None


def _vs_base(variant: Mapping, base: Mapping) -> tuple[object, object]:
    """The row's pooled rank IC and mean top-5% excess return, each minus the base row's; None when unmeasured."""
    if variant.get("status") != "run" or base.get("status") != "run":
        return None, None
    ic, base_ic = (((v.get("summary") or {}).get("pooled") or {}).get("rank_ic") for v in (variant, base))
    rank_ic = None if _missing(ic) or _missing(base_ic) else ic - base_ic

    def measured(v: Mapping) -> set:
        pooled = (v.get("top_slice") or {}).get("pooled") or {}
        return {h for h, row in pooled.items() if not _missing((row or {}).get("top_excess"))}

    both = measured(variant) & measured(base)  # the horizons both rows have
    top = None if not both else _mean_top_excess(variant, both) - _mean_top_excess(base, both)
    return rank_ic, top


def _new_data_table(market: Mapping) -> list[str]:
    """Each data group row against the base row it adds its group to, then the combined row."""
    variants = market.get("variants") or {}
    base = variants.get(_GROUP_BASE)
    rows = [(group, name) for name, group in _GROUP_ROWS.items() if name in variants]
    if base is None or not rows:
        return []
    combined = market.get("combined")
    if combined and combined in variants:
        rows.append((combined, combined))
    lines = [
        "### Did the new data help?",
        "",
        "| Group | Rank IC vs base | Top 5% vs base | Decision |",
        "| --- | --- | --- | --- |",
    ]
    for label, name in rows:
        rank_ic, top = _vs_base(variants[name], base)
        lines.append(f"| {label} | {_fmt(rank_ic, '+.3f')} | {_signed(top)} | {_decision(name, market)} |")
    return lines


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
        f"horizons {days}" + (f", top_n {raw['top_n']}" if raw.get("top_n") is not None else "")
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


def _count(value: object) -> str:
    return "—" if _missing(value) else str(int(value))


def _points(value: object) -> str:
    return "—" if _missing(value) else f"{value * 100:.1f} pts"


def _exit_plan_check(block: Mapping) -> list[str]:
    """How each class's exit plans held up on history (`exit_check.verdicts`)."""
    lines = ["### Exit plan check", ""]
    if "error" in block:
        return [*lines, f"Failed: {block['error']}"]
    lines += [f"Model: {block.get('model') or '—'}, plan version {block.get('plan_version', '—')}", ""]
    classes = block.get("classes") or {}
    if not classes:
        return [*lines, "No class had enough pairs for a verdict (not validated yet)."]
    lines += [
        "| Class | Pairs | Touch rate (stated 33%) | Coverage (stated 80%) | Worst break-even bin "
        "| Worst stop-first bin | Order gain | Order t (days) | Folds not worse | Result |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for name, v in classes.items():
        lines.append(
            f"| {name} | {_count(v.get('pairs'))} | {_pct(v.get('touch_rate'))} | {_pct(v.get('coverage'))} "
            f"| {_points(v.get('breakeven_worst_bin'))} | {_points(v.get('stop_first_worst_bin'))} "
            f"| {_signed(v.get('order_gain'))} | {_fmt(v.get('order_t'), '+.2f')} ({_count(v.get('order_days'))}) "
            f"| {_count(v.get('order_folds_not_worse'))} of {_count(v.get('folds'))} | {v.get('result') or '—'} |"
        )
    lines += [
        "",
        "The order's value fails only when it tests measurably worse than holding (t under -2 on "
        "the sample days' mean gains, at least 20 days).",
    ]
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
    ] + ([
        f"- the accepted configuration keeps its place with calibration up to "
        f"{constants['incumbent_calibration_pts']:g} points; a newcomer needs {cal:g}",
    ] if "incumbent_calibration_pts" in constants else [])


def _garch_line(variant: Mapping) -> str | None:
    """One diagnostic line for a garch variant, or None when the key is absent."""
    stored = variant.get("garch")
    if not isinstance(stored, Mapping):
        return None
    fallbacks = stored.get("fallbacks", 0)
    line = (
        f"GARCH: {fallbacks} assets without a fit (under 500 returns, or no stable fit)"
    )
    ranges = stored.get("range")
    if not isinstance(ranges, Mapping) or not ranges:
        return line + "."
    bits = []
    for horizon in sorted(ranges, key=lambda h: int(h)):
        info = ranges[horizon]
        if not isinstance(info, Mapping):
            continue
        if info.get("adopted") and not _missing(info.get("s")):
            bits.append(f"{horizon}d s={info['s']:g} (used)")
        else:
            bits.append(f"{horizon}d not used")
    if not bits:
        return line + "."
    return line + "; range blend " + ", ".join(bits) + "."


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
        if "skipped" in market:
            lines += [f"Skipped: {market['skipped']}", ""]
            continue
        lines += [_choice_line(market), ""]
        if new_data := _new_data_table(market):
            lines += [*new_data, ""]
        lines += ["### Ablations", ""]
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
            if (variant.get("top_slice") or {}).get("pooled"):
                lines += _top_slice_table(name, variant)
                lines.append("")
            if "alpha_rank_ic" in variant or "fallback_count" in variant:
                lines.append(
                    "Factor diagnostic: rank IC of q50_alpha vs alpha "
                    f"{_fmt(variant.get('alpha_rank_ic'), '.3f')}; "
                    f"fallbacks {variant.get('fallback_count', 0)}."
                )
            if variant.get("french"):
                lines.append(f"Kenneth French cross-check: {variant['french']}")
            if "alpha_rank_ic" in variant or variant.get("french"):
                lines.append("")
            if (garch_line := _garch_line(variant)) is not None:
                lines += [garch_line, ""]
            if isinstance(variant.get("policy"), Mapping):
                lines += _policy_table(variant)
                lines.append("")
        if isinstance(market.get("exit_plan"), Mapping):
            lines += [*_exit_plan_check(market["exit_plan"]), ""]
    lines += _how(report["constants"])
    lines.append("")
    return "\n".join(lines)


def write_reports(report: Mapping, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "benchmark-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (out / "benchmark-report.md").write_text(render_markdown(report), encoding="utf-8")
