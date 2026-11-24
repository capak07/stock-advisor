from dataclasses import replace
from datetime import date

from advisor.collectors.sec import SecUnavailable
from advisor.runners.warnings import (
    filing_warnings,
    mentions_reverse_split,
    split_warning,
    warnings_for,
)
from runner_data import filing

AS_OF = date(2026, 11, 24)


class Sec:
    """A stand-in SEC client: one company, its filings and their documents (an exception is raised)."""

    def __init__(self, filings, documents=None):
        self._filings = filings
        self._documents = documents or {}
        self.fetched = []

    def cik_for(self, symbol):
        return 1888014

    def filings(self, cik):
        return self._filings

    def document(self, cik, f):
        self.fetched.append(f.filing_date)
        body = self._documents[f.accession]
        if isinstance(body, Exception):
            raise body
        return body


def test_akans_f1a_is_a_pending_share_sale():
    [w] = filing_warnings([filing("F-1/A", date(2026, 11, 20))], AS_OF)
    assert w == {"kind": "share_sale", "form": "F-1/A", "filed": "2026-11-20",
                 "text": "Filed a F-1/A on Nov 20: a share sale may be pending."}


def test_a_fresh_prospectus_wins_and_old_filings_are_ignored():
    got = filing_warnings([filing("S-3", date(2026, 10, 1)), filing("424B5", date(2026, 11, 2))], AS_OF)
    assert [w["form"] for w in got] == ["424B5"]
    assert filing_warnings([filing("S-1", date(2026, 8, 1)), filing("424B5", date(2026, 10, 1))], AS_OF) == []


def test_item_301_and_503_warn():
    got = filing_warnings([filing("8-K", date(2026, 5, 20), ("3.01",)), filing("8-K", date(2026, 11, 1), ("5.03", "9.01"))], AS_OF)
    assert {w["kind"] for w in got} == {"deficiency", "reverse_split"}


def test_a_recorded_reverse_split_names_its_ratio():
    assert split_warning([(date(2026, 4, 13), 1 / 4.5), (date(2026, 11, 23), 1 / 25)], AS_OF)["text"] == "Reverse split 1-for-25 on Nov 23."
    assert split_warning([(date(2026, 4, 13), 0.2)], AS_OF) is None            # older than 90 days
    assert split_warning([(date(2026, 11, 2), 2.0)], AS_OF) is None            # a forward split


def test_reverse_split_wording():
    assert mentions_reverse_split(b"effected a 5-for-1 Reverse Stock Split of its common shares")
    assert mentions_reverse_split(b"a share consolidation") and not mentions_reverse_split(b"stock split dividend")


def test_reverse_split_wording_across_a_line_break_or_a_non_breaking_space():
    assert mentions_reverse_split(b"approved a reverse\r\n  stock split of 1-for-10")
    assert mentions_reverse_split(b"a reverse&nbsp;share&nbsp;split") and mentions_reverse_split(b"a share&#160;consolidation")
    assert mentions_reverse_split("a reverse\xa0split".encode())


def test_a_6k_without_a_document_is_not_fetched():
    empty = replace(filing("6-K", date(2026, 11, 18)), primary_document="")
    sec = Sec([empty])
    assert warnings_for("AKAN", AS_OF, sec=sec, splits=[]) == ([], True)
    assert sec.fetched == []


def test_without_sec_the_signal_keeps_only_the_split_warning_and_says_unchecked():   # Review Focus 5
    assert warnings_for("AKAN", AS_OF, sec=None, splits=[]) == ([], False)
    class Down:
        def cik_for(self, symbol): raise SecUnavailable("down")
    assert warnings_for("AKAN", AS_OF, sec=Down(), splits=[(date(2026, 11, 23), 0.04)])[1] is False
    class NoCik:
        def cik_for(self, symbol): return None
    assert warnings_for("AKAN", AS_OF, sec=NoCik(), splits=[]) == ([], False)


def test_a_failing_filing_list_keeps_the_split_warning_and_says_unchecked():
    class Down(Sec):
        def filings(self, cik): raise SecUnavailable("down")
    got, checked = warnings_for("AKAN", AS_OF, sec=Down([]), splits=[(date(2026, 11, 23), 0.04)])
    assert ([w["text"] for w in got], checked) == (["Reverse split 1-for-25 on Nov 23."], False)


def test_one_of_each_kind_in_a_fixed_order_and_the_recorded_split_comes_first():
    sec = Sec([filing("8-K", date(2026, 5, 20), ("3.01",)), filing("8-K", date(2026, 11, 1), ("5.03",)),
               filing("8-K", date(2026, 8, 1), ("3.01",)), filing("S-1", date(2026, 9, 1)),
               filing("F-1/A", date(2026, 11, 20)), filing("6-K", date(2026, 11, 3))])
    got, checked = warnings_for("AKAN", AS_OF, sec=sec, splits=[(date(2026, 11, 23), 0.04)])
    assert checked is True
    assert [(w["kind"], w["filed"]) for w in got] == [
        ("share_sale", "2026-11-20"), ("reverse_split", "2026-11-23"), ("deficiency", "2026-08-01")]
    assert sec.fetched == []                     # a known split needs no 6-K read


def test_the_8k_item_503_comes_before_the_6ks():
    sec = Sec([filing("8-K", date(2026, 11, 1), ("5.03",)), filing("6-K", date(2026, 11, 3))])
    got, _ = warnings_for("AKAN", AS_OF, sec=sec, splits=[])
    assert [w["text"] for w in got] == ["Filed an 8-K (item 5.03) on Nov 1: a charter change, often a reverse split."]
    assert sec.fetched == []


def test_a_6k_that_mentions_a_reverse_split_warns_and_a_failed_read_is_skipped():
    failed, quiet, named = filing("6-K", date(2026, 11, 18)), filing("6-K", date(2026, 11, 15)), filing("6-K", date(2026, 11, 10))
    sec = Sec([named, failed, quiet], {failed.accession: SecUnavailable("down"), quiet.accession: b"results",
                                       named.accession: b"approved a share consolidation"})
    got, checked = warnings_for("AKAN", AS_OF, sec=sec, splits=[])
    assert (got, checked) == ([{"kind": "reverse_split", "form": "6-K", "filed": "2026-11-10",
                                "text": "A 6-K on Nov 10 mentions a reverse split."}], True)
    assert sec.fetched == [date(2026, 11, 18), date(2026, 11, 15), date(2026, 11, 10)]


def test_only_the_3_most_recent_6ks_in_90_days_are_read():
    older, *recent = [filing("6-K", day) for day in (date(2026, 11, 1), date(2026, 11, 5), date(2026, 11, 10),
                                                     date(2026, 11, 20))]
    stale = filing("6-K", date(2026, 8, 1))
    docs = {f.accession: b"a reverse split" if f in (older, stale) else b"nothing" for f in (older, stale, *recent)}
    sec = Sec([stale, older, *recent], docs)
    assert warnings_for("AKAN", AS_OF, sec=sec, splits=[]) == ([], True)
    assert sec.fetched == [date(2026, 11, 20), date(2026, 11, 10), date(2026, 11, 5)]


def test_filings_after_the_day_are_not_seen():
    assert filing_warnings([filing("424B4", date(2026, 11, 25)), filing("8-K", date(2026, 11, 30), ("3.01",))], AS_OF) == []
