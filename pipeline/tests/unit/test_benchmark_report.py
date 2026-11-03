import json
import math
import os
import subprocess
import sys

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
        "incumbent_calibration_pts": 5.5,
        "seed": 7,
        "bag_seeds": [7, 8, 9],
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
    assert "- the accepted configuration keeps its place with calibration up to 5.5 points" in how
    write_reports(REPORT, tmp_path)
    assert json.loads((tmp_path / "benchmark-report.json").read_text()) == REPORT
    assert (tmp_path / "benchmark-report.md").read_text() == md


def test_the_markdown_report_is_utf8_whatever_the_machine_locale(tmp_path):
    # on Windows the default file encoding is cp1252, and the report's dashes came out as "�"
    script = (
        "import json, sys; from pathlib import Path; from advisor.benchmark.report import write_reports; "
        "write_reports(json.loads(sys.argv[1]), Path(sys.argv[2]))"
    )
    env = {**os.environ, "PYTHONUTF8": "0", "PYTHONCOERCECLOCALE": "0", "LC_ALL": "C", "LANG": "C"}
    done = subprocess.run(
        [sys.executable, "-c", script, json.dumps(REPORT), str(tmp_path)], env=env, capture_output=True, text=True
    )
    assert done.returncode == 0, done.stderr
    assert (tmp_path / "benchmark-report.md").read_bytes().decode("utf-8") == render_markdown(REPORT)


def test_ablation_rows_print_in_a_fixed_order_whatever_order_the_dict_arrives_in():
    messy = json.loads(json.dumps(REPORT))
    baseline = messy["markets"]["TSX"]["variants"]["baseline"]
    not_built = {"status": "not built", "plan": "later"}
    messy["markets"]["TSX"]["variants"] = {
        "garch": not_built,
        "factors": not_built,
        "ranker": not_built,
        "extras": not_built,
        "ranker+extras": not_built,
        "ranker+extras+bagged": not_built,
        "baseline": baseline,
        "full+policy": not_built,
        "factors+garch": not_built,
    }
    ablation = render_markdown(messy).split("### Ablations", 1)[1].split("### Outer", 1)[0]
    names = [
        line.split("|")[1].strip()
        for line in ablation.splitlines()
        if line.startswith("| ") and "Variant" not in line and "---" not in line
    ]
    assert names == [
        "baseline", "factors", "ranker", "extras", "ranker+extras", "ranker+extras+bagged", "garch",
        "factors+garch", "full+policy",
    ]


def _score(pooled: dict) -> dict:
    return {
        "per_period": [pooled], "pooled": pooled, "feasible": bool(pooled["trades"] >= 30),
        "failures": [], "objective": pooled["sharpe"],
    }


def test_the_policy_table_shows_both_books_and_dashes_an_empty_default():
    messy = json.loads(json.dumps(REPORT))
    empty = {
        "trades": 0, "trades_per_month": None, "mean_net_pct": None, "hit_rate_net": None,
        "beat_rate": None, "mean_p": None, "sharpe": None, "max_drawdown": 0.0,
    }
    tuned = {
        "trades": 40, "trades_per_month": 4.0, "mean_net_pct": 1.2, "hit_rate_net": 0.55,
        "beat_rate": 0.52, "mean_p": 0.60, "sharpe": 0.8, "max_drawdown": 0.12,
    }
    one = {"p_buy": 0.6, "p_sell": 0.42, "swing_atr": 2.0, "position_atr": 3.0, "trail_atr": 2.5,
           "rule": "ratio", "horizons": None}
    fold_reason = "no stage-1 combination met the limits: best failed on only 4 trades (needs 30)"
    messy["markets"]["TSX"]["variants"]["full+policy"] = {
        "status": "run",
        "model": "baseline",
        "policy": {
            "default": _score(empty),
            "candidate": _score(tuned),
            "per_fold": [one, None, one],
            "per_fold_reasons": ["inner tune", fold_reason, "inner tune"],
            "final": None,
            "final_reason": "the whole-history tune found nothing",
        },
    }
    messy["markets"]["TSX"]["decisions"]["full+policy"] = {
        "accepted": False, "reasons": [f"outer fold 2: {fold_reason}"],
    }
    md = render_markdown(messy)
    assert "| full+policy | run | — | — | — | rejected: outer fold 2: " in md
    assert "### Outer folds: full+policy" not in md
    table = md.split("### Policy (folds 1–3)", 1)[1]
    today = next(line for line in table.splitlines() if line.startswith("| today's rules"))
    tuned_row = next(line for line in table.splitlines() if line.startswith("| tuned"))
    assert "—" in today and "nan" not in today.lower() and "None" not in today
    assert "| tuned | 40 | 4.0 | 1.20% | 55% | 0.80 | 12% | 60% vs 52% |" == tuned_row
    assert "Fold 1: p_buy 0.60" in table
    assert f"Fold 2: no policy — {fold_reason}" in table
    assert "No final policy: the whole-history tune found nothing" in table
    assert "Decision: rejected: outer fold 2: " in table


def test_nan_and_none_render_as_dashes_not_the_words():
    messy = json.loads(json.dumps(REPORT))
    messy["markets"]["TSX"]["variants"]["baseline"]["summary"]["pooled"]["rank_ic"] = None
    messy["markets"]["TSX"]["variants"]["baseline"]["model"]["1"]["5"]["calibration_pts"] = math.nan
    md = render_markdown(messy)
    assert "nan" not in md.lower() and "None" not in md


def test_an_older_report_without_the_incumbent_limit_still_renders():
    old = {**REPORT, "constants": {k: v for k, v in REPORT["constants"].items() if k != "incumbent_calibration_pts"}}
    how = render_markdown(old)[render_markdown(old).index("## How decisions are made"):]
    assert "keeps its place" not in how
