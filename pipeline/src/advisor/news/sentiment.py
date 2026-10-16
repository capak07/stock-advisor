"""Headline sentiment with FinBERT (spec §4.3 stage 5): ProsusAI/finbert on the CPU.

**Model.** About 440 MB, pinned to a revision, and downloaded once into the Hugging Face cache, which
the run workflow keeps between runs. Its licence (CC BY-NC-SA 4.0) allows this personal,
non-commercial use.

**Dependencies.** torch (CPU build) and transformers are the optional `nlp` extra. The scheduled run
installs them and tests don't. Without them, stories get no sentiment rather than failing the run.

**Score.** A story's score is P(positive) minus P(negative), in [-1, 1]. The model's labels are read
from its config, because they come in the order positive, negative, neutral.
"""

from collections.abc import Callable, Sequence

FINBERT = "ProsusAI/finbert"
FINBERT_REVISION = "0bc2ac10dda6929bcb1f77ccc43c7ec5c424f031"
BATCH = 32
MAX_TOKENS = 64

Scorer = Callable[[Sequence[str]], list[float]]


def load_finbert() -> Scorer | None:
    """A FinBERT scorer, or None when the `nlp` extra isn't installed."""
    try:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
    except ImportError:
        return None
    tokenizer = AutoTokenizer.from_pretrained(FINBERT, revision=FINBERT_REVISION)
    model = AutoModelForSequenceClassification.from_pretrained(
        FINBERT, revision=FINBERT_REVISION, use_safetensors=True
    )
    model.eval()
    label = {name.lower(): index for index, name in model.config.id2label.items()}
    positive, negative = label["positive"], label["negative"]

    def score(titles: Sequence[str]) -> list[float]:
        scores: list[float] = []
        with torch.inference_mode():
            for start in range(0, len(titles), BATCH):
                batch = tokenizer(
                    list(titles[start:start + BATCH]),
                    padding=True,
                    truncation=True,
                    max_length=MAX_TOKENS,
                    return_tensors="pt",
                )
                probabilities = model(**batch).logits.softmax(dim=-1)
                scores.extend((probabilities[:, positive] - probabilities[:, negative]).tolist())
        return scores

    return score
