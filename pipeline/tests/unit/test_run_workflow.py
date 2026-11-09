from pathlib import Path

WORKFLOW = (Path(__file__).parents[3] / ".github" / "workflows" / "run.yml").read_text(encoding="utf-8")


def test_dispatch_offers_auto_as_the_default_kind():
    # an outside scheduler dispatches kind=auto when GitHub's own crons arrive hours late
    assert "default: auto" in WORKFLOW
    assert "- auto" in WORKFLOW


def test_auto_runs_the_guarded_path_without_force_kind():
    # kind=auto must not force: the slot window and the once-per-kind-per-date guard still apply
    assert '"$FORCE_KIND" != "auto"' in WORKFLOW


def test_the_github_crons_stay_as_a_backstop_for_both_dst_offsets():
    for cron in ("15 12", "15 13", "15 16", "15 17", "15 19", "15 20"):
        assert f'cron: "{cron} * * 1-5"' in WORKFLOW
