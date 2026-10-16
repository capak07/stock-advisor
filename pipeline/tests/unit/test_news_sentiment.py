import sys

from advisor.news.sentiment import FINBERT_REVISION, load_finbert


def test_without_the_nlp_extra_there_is_no_scorer(monkeypatch):
    monkeypatch.setitem(sys.modules, "transformers", None)  # makes `import transformers` fail
    assert load_finbert() is None


def test_the_model_is_pinned_to_a_revision():
    assert len(FINBERT_REVISION) == 40  # a full commit hash, so the cached model never changes
