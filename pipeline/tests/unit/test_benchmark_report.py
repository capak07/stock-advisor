import json
import math

from advisor.benchmark.report import SURVIVORSHIP, render_markdown, write_reports

HORIZON = {
    "rank_ic": 0.061,
    "pinball": 0.01234,
    "calibration_pts": 3.2,
    "coverage_10_90": 0.81,
    "rows": 10,
}
FOLD0 = {**HORIZON, "calibration_pts": None}
SUMMARY = {"rank_ic": 0.061, "pinball": 0.01234}
POLICY = {
    "trades": 2,
    "trades_per_month": 1.0,
    "mean_net_pct": 0.42,
    "hit_rate_net": 0.81,
    "beat_rate": 0.70,
    "mean_p": 0.75,
    "claimed_gap_pts": 5.0,
}
REPORT = {
    "run_id": 3,
    "started_at": "2026-11-01T09:00:00+00:00",
    "git_sha": "abc1234",
    "status": "success",
    "constants": {
        "outer_folds": 4,
        "min_train_years": 2.0,
        "inner_splits": 3,
        "inner_min_train_years": 1.0,
        "pinball_tolerance": 0.005,
        "min_folds_improved": 3,
        "max_calibration_pts": 5.0,
        "seed": 7,
        "rounds": 200,
        "sample_every": 10,
    },
    "markets": {
        "TSX": {
            "horizons": [5],
            "variants": {
                "baseline": {
                    "status": "run",
                    "seconds": 55.0,
                    "model": {"0": {"5": FOLD0}, "1": {"5": HORIZON}, "pooled": {"5": HORIZON}},
                    "summary": {"0": SUMMARY, "1": SUMMARY, "pooled": SUMMARY},
                    "policy": {"1": POLICY, "pooled": POLICY},
                },
                "factors": {"status": "not built", "plan": "Plan 6c"},
            },
            "decisions": {},
            "chosen": "baseline",
            "accepted": {
                "changed": True,
                "reason": "first benchmark: today's model",
                "config": {"version": 1},
            },
        },
        "US": {"error": "FileNotFoundError: no prices"},
    },
}


def test_the_report_names_the_choice_the_survivorship_bias_and_the_rules(tmp_path):
    md = render_markdown(REPORT)
    assert md.startswith("# Benchmark report — 2026-11-01 (abc1234)")
    head, _, rest = md.partition("\n## ")
    assert SURVIVORSHIP in head and md.count(SURVIVORSHIP) == 1
    assert "| factors | arrives with Plan 6c | — | — | — | — |" in md
    us = rest[rest.index("## US"): rest.index("## How")]
    assert "Failed: FileNotFoundError: no prices" in us
    assert "— (no earlier predictions)" in md
    assert "nan" not in md.lower() and "None" not in md
    how = md[md.index("## How decisions are made"):]
    assert "0.5%" in how and "3 of 4" in how
    write_reports(REPORT, tmp_path)
    assert json.loads((tmp_path / "benchmark-report.json").read_text()) == REPORT
    assert (tmp_path / "benchmark-report.md").read_text() == md


def test_nan_and_none_render_as_dashes_not_the_words():
    messy = json.loads(json.dumps(REPORT))
    messy["markets"]["TSX"]["variants"]["baseline"]["summary"]["pooled"]["rank_ic"] = None
    messy["markets"]["TSX"]["variants"]["baseline"]["model"]["1"]["5"]["calibration_pts"] = math.nan
    md = render_markdown(messy)
    assert "nan" not in md.lower() and "None" not in md
