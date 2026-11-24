"""Warnings on a signal: a share sale, a reverse split or a listing notice, from SEC filings and Yahoo's splits."""

import re
from collections.abc import Callable, Sequence
from datetime import date

from advisor.collectors.sec import Filing, SecEdgar

REGISTRATIONS = {"F-1", "S-1", "F-3", "S-3"}
REVERSE_SPLIT = re.compile(r"reverse (stock |share )?split|share consolidation", re.IGNORECASE)
SIX_KS_READ = 3


def _day(d: date) -> str:
    return f"{d:%b} {d.day}"  # "Nov 20"; Windows has no %-d


def _warning(kind: str, form: str, filed: date, text: str) -> dict:
    return {"kind": kind, "form": form, "filed": filed.isoformat(), "text": text}


def _within(filed: date, as_of: date, days: int) -> bool:
    return 0 <= (as_of - filed).days <= days


def _latest(filings: Sequence[Filing], as_of: date, days: int, match: Callable[[Filing], bool]) -> Filing | None:
    found = [f for f in filings if _within(f.filing_date, as_of, days) and match(f)]
    return max(found, key=lambda f: f.filing_date, default=None)


def _is_registration(f: Filing) -> bool:
    return f.form.removesuffix("/A") in REGISTRATIONS


def _share_sale(filings: Sequence[Filing], as_of: date) -> dict | None:
    if prospectus := _latest(filings, as_of, 30, lambda f: f.form.startswith("424B")):
        day = prospectus.filing_date
        return _warning("share_sale", prospectus.form, day,
                        f"Filed a {prospectus.form} prospectus on {_day(day)}: shares are being sold.")
    if registration := _latest(filings, as_of, 90, _is_registration):
        day = registration.filing_date
        return _warning("share_sale", registration.form, day,
                        f"Filed a {registration.form} on {_day(day)}: a share sale may be pending.")
    return None


def _charter_change(filings: Sequence[Filing], as_of: date) -> dict | None:
    if f := _latest(filings, as_of, 90, lambda f: f.form == "8-K" and "5.03" in f.items):
        return _warning("reverse_split", f.form, f.filing_date,
                        f"Filed an 8-K (item 5.03) on {_day(f.filing_date)}: a charter change, often a reverse split.")
    return None


def _listing_notice(filings: Sequence[Filing], as_of: date) -> dict | None:
    if f := _latest(filings, as_of, 365, lambda f: f.form == "8-K" and "3.01" in f.items):
        return _warning("deficiency", f.form, f.filing_date,
                        f"Filed an 8-K (item 3.01) on {_day(f.filing_date)}: an exchange listing notice.")
    return None


def _in_order(*warnings: dict | None) -> list[dict]:
    return [w for w in warnings if w is not None]


def filing_warnings(filings: Sequence[Filing], as_of: date) -> list[dict]:
    """At most one warning per kind, from the most recent filing that raises it; no 6-K is read here."""
    return _in_order(_share_sale(filings, as_of), _charter_change(filings, as_of), _listing_notice(filings, as_of))


def split_warning(splits: Sequence[tuple[date, float]], as_of: date) -> dict | None:
    """The most recent reverse split (a Yahoo ratio below 1) in the last 90 days."""
    reverse = [(day, ratio) for day, ratio in splits if 0 < ratio < 1 and _within(day, as_of, 90)]
    if not reverse:
        return None
    day, ratio = max(reverse)
    return _warning("reverse_split", "split", day, f"Reverse split 1-for-{round(1 / ratio)} on {_day(day)}.")


def mentions_reverse_split(document: bytes) -> bool:
    return REVERSE_SPLIT.search(document.decode("utf-8", errors="replace")) is not None


def _six_k(sec: SecEdgar, cik: int, filings: Sequence[Filing], as_of: date) -> dict | None:
    """The newest of the 3 most recent 6-Ks in 90 days that mentions a reverse split. Best effort."""
    six_ks = [f for f in filings if f.form == "6-K" and _within(f.filing_date, as_of, 90)]
    for f in sorted(six_ks, key=lambda f: f.filing_date, reverse=True)[:SIX_KS_READ]:
        try:
            named = mentions_reverse_split(sec.document(cik, f))
        except Exception:  # noqa: BLE001 - an unread 6-K only loses this one check
            continue
        if named:
            return _warning("reverse_split", f.form, f.filing_date,
                            f"A 6-K on {_day(f.filing_date)} mentions a reverse split.")
    return None


def warnings_for(symbol: str, as_of: date, *, sec: SecEdgar | None,
                 splits: Sequence[tuple[date, float]]) -> tuple[list[dict], bool]:
    """The signal's warnings, and whether its filings were checked. Without them only a recorded split shows."""
    split = split_warning(splits, as_of)
    if sec is None:
        return _in_order(split), False
    try:
        cik = sec.cik_for(symbol)
        if cik is None:
            return _in_order(split), False
        filings = sec.filings(cik)
    except Exception:  # noqa: BLE001 - SEC being down must not hold up the signal
        return _in_order(split), False
    reverse = split or _charter_change(filings, as_of) or _six_k(sec, cik, filings, as_of)
    return _in_order(_share_sale(filings, as_of), reverse, _listing_notice(filings, as_of)), True
