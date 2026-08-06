"""Question-quality head — ranks the PM Review Queue by "is this worth asking".

Trained offline against DeepSeek verdicts on 2508 unique questions from 250
deals, then distilled into two dep-free pieces:

* ``scores`` — a table of precomputed semantic scores keyed by normalized
  question text. Template asks repeat verbatim across deals, so this covers
  53% of the cards on a deal the model has never seen.
* ``fallback_weights`` — a logistic model over structural features, used for
  text the table has never seen.

Inference is a dict lookup and a dot product. Core declares no ML dependencies
and this module adds none; the embedder that produced the table runs offline in
training only.

Measured on held-out deals (top-12 good rate, 5 deal splits):

    engine order today                 30.7%
    + rules gate                       36.6%
    + this head                        47.5%
    live embedder at request time      48.7%   (not worth torch in the image)
    oracle / perfect ranking           79.7%
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Mapping

from orbitbrief_core.pm_handoff.models import GapCard
from orbitbrief_core.pm_handoff.question_features import extract_features

_MODEL_PATH = Path(__file__).with_name("data") / "question_quality_model.json"
_MODEL: dict | None = None
_MISSING = False


def _normalize(text: str) -> str:
    return re.sub(r"\W+", " ", (text or "").lower()).strip()


def load_model() -> dict | None:
    """Load and cache the artifact. A missing/corrupt file disables the head."""
    global _MODEL, _MISSING
    if _MODEL is not None or _MISSING:
        return _MODEL
    try:
        with _MODEL_PATH.open(encoding="utf-8") as fh:
            model = json.load(fh)
        if not isinstance(model, dict) or "scores" not in model:
            raise ValueError("missing scores table")
        _MODEL = model
    except (OSError, ValueError, json.JSONDecodeError):
        # Ranking must never take the brief down — fall back to pool order.
        _MISSING = True
        _MODEL = None
    return _MODEL


def _card_fields(card: GapCard | Mapping[str, Any]) -> tuple[str, str, str, list, str]:
    if isinstance(card, GapCard):
        return (
            card.suggested_open_question or card.message or "",
            card.rule_id or "",
            card.severity or "",
            list(card.sources or []),
            card.observed_summary or "",
        )
    return (
        str(card.get("suggested_open_question") or card.get("message") or ""),
        str(card.get("rule_id") or ""),
        str(card.get("severity") or ""),
        list(card.get("sources") or []),
        str(card.get("observed_summary") or ""),
    )


def score_card(card: GapCard | Mapping[str, Any], model: dict | None = None) -> float | None:
    """Quality score for one card; ``None`` when the head is unavailable.

    Higher is better. The value is a logit, not a probability — it is only ever
    used to sort, so no calibration is implied.
    """
    model = model if model is not None else load_model()
    if not model:
        return None
    question, rule_id, severity, sources, observed = _card_fields(card)
    if not question:
        return None

    hit = model.get("scores", {}).get(_normalize(question))
    if hit is not None:
        return float(hit)

    weights = model.get("fallback_weights") or {}
    if not weights:
        return None
    feats = extract_features(
        question=question,
        rule_id=rule_id,
        severity=severity,
        sources=sources,
        observed=observed,
    )
    z = float(model.get("fallback_intercept") or 0.0)
    for name, value in feats.items():
        w = weights.get(name)
        if w:
            z += w * value
    return z


def probability(logit: float) -> float:
    """Squash a score for display. Not used for ranking."""
    if logit < -30:
        return 0.0
    if logit > 30:
        return 1.0
    return 1.0 / (1.0 + math.exp(-logit))
