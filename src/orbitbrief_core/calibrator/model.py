"""Calibration math: linear combiner + Platt-scaling sigmoid.

Linear combiner
===============

Hand-tuned default weights (sum to 1.0) prioritize parser /
packet / claim confidences and let validator outcomes dominate as
hard gates:

    raw = Σ w_i · feature_i      ∈ [0, 1]

We then apply a hard mask: if ``validator_pass == 0`` we cap raw
at 0.20 (ensuring blockers always end up in the review queue),
and if ``validator_warning == 1`` we cap raw at 0.80.

Platt scaling
=============

After fitting on past PM decisions we have parameters ``(a, b)``
such that ``p(accept) = sigmoid(a·raw + b)``. The default
``a=1.0, b=0.0`` is the identity; calling :meth:`PlattCalibrator.fit`
re-derives them via gradient descent on the log-loss.

Why not scikit-learn? The whole calibrator stays stdlib + numpy-
free so deployments don't pick up a heavy science stack just to
do logistic regression on a few hundred examples.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Iterable

from orbitbrief_core.calibrator.signals import SignalVector


@dataclass(frozen=True)
class SignalWeights:
    """Linear-combiner weights. Must sum to 1.0 (validated)."""

    parser_confidence: float = 0.18
    graph_confidence: float = 0.05
    packet_confidence: float = 0.18
    claim_confidence: float = 0.12
    contradiction_density: float = 0.10
    retrieval_coverage: float = 0.08
    ambiguity_penalty: float = 0.10  # applied to (1 - ambiguity)
    example_similarity: float = 0.05
    validator_pass: float = 0.10
    validator_warning_penalty: float = 0.04  # applied to (1 - validator_warning)

    def __post_init__(self) -> None:
        total = sum(self.as_dict().values())
        # Allow tiny float drift.
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"SignalWeights must sum to 1.0; got {total:.6f}"
            )

    def as_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass
class PlattCalibrator:
    """Sigmoid post-calibration: p = 1 / (1 + exp(-(a·x + b)))."""

    a: float = 1.0
    b: float = 0.0

    def predict(self, x: float) -> float:
        z = self.a * x + self.b
        # Standard numerically-stable sigmoid.
        if z >= 0:
            ez = math.exp(-z)
            return 1.0 / (1.0 + ez)
        ez = math.exp(z)
        return ez / (1.0 + ez)

    def fit(
        self,
        raw_scores: list[float],
        labels: list[int],
        *,
        max_iters: int = 100,
        tol: float = 1e-7,
    ) -> None:
        """Fit ``(a, b)`` via Newton-Raphson on the log-loss.

        Newton-Raphson converges quadratically for logistic
        regression, so we get a tight fit in a handful of iterations
        — much faster (and tighter) than gradient descent for the
        Platt-scaling shapes we see in production. We add a tiny
        ridge regularization (1e-6) to keep the Hessian invertible
        on degenerate inputs.

        Mutates ``self`` in place. ``labels`` are 0/1 ints.
        """
        if len(raw_scores) != len(labels):
            raise ValueError("fit: raw_scores and labels length mismatch")
        if not raw_scores:
            return
        # Initialize from log-odds of the base rate so we never have
        # to chase a from 1.0 if the data implies a >> 1.
        n = len(raw_scores)
        pos = sum(labels)
        if 0 < pos < n:
            base_logit = math.log(pos / (n - pos))
        else:
            base_logit = 0.0
        a, b = self.a, base_logit
        ridge = 1e-6

        for _ in range(max_iters):
            # Build gradient (g) and Hessian (H) of -log-likelihood.
            g0 = g1 = 0.0
            h00 = h01 = h11 = 0.0
            for x, y in zip(raw_scores, labels):
                p = _sigmoid(a * x + b)
                err = p - y
                g0 += err * x
                g1 += err
                w = p * (1.0 - p)
                h00 += w * x * x
                h01 += w * x
                h11 += w
            # Ridge regularization.
            h00 += ridge
            h11 += ridge
            det = h00 * h11 - h01 * h01
            if abs(det) < 1e-18:
                break
            # Newton step: theta -= H^-1 g.
            da = (h11 * g0 - h01 * g1) / det
            db = (-h01 * g0 + h00 * g1) / det
            a_new = a - da
            b_new = b - db
            if abs(a_new - a) < tol and abs(b_new - b) < tol:
                a, b = a_new, b_new
                break
            a, b = a_new, b_new

        self.a = a
        self.b = b


@dataclass
class LearnedCombiner:
    """Trained logistic head over the 10 SignalVector features -> P(accept).

    The neural head for the brain pipeline. Replaces the hand-tuned linear
    combiner + identity Platt sigmoid — whose max output sigmoid(1.0)=0.73 can
    never reach the 0.80 auto-accept threshold, so the rule path auto-accepts
    NOTHING. Loaded from a tiny JSON artifact (tools/train_calibration_head.py,
    ~11 floats); no torch/sklearn at runtime. Guess-free: CalibrationModel falls
    back to the hand-tuned path when no head is configured, and the blocker
    safety cap is preserved here regardless.
    """

    weights: dict[str, float]
    bias: float
    mean: dict[str, float]
    std: dict[str, float]
    features: tuple[str, ...]
    blocker_cap: float = 0.20

    @classmethod
    def from_json(cls, path: str) -> "LearnedCombiner":
        import json

        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
        feats = tuple(d.get("features") or list(d["weights"].keys()))
        return cls(
            weights={k: float(v) for k, v in d["weights"].items()},
            bias=float(d.get("bias", 0.0)),
            mean={k: float(v) for k, v in (d.get("feature_mean") or {}).items()},
            std={k: float(v) for k, v in (d.get("feature_std") or {}).items()},
            features=feats,
        )

    def prob(self, sig: SignalVector) -> float:
        s = sig.as_features()
        z = self.bias
        for f in self.features:
            denom = self.std.get(f, 1.0) or 1.0
            x = (float(s.get(f, 0.0)) - self.mean.get(f, 0.0)) / denom
            z += self.weights.get(f, 0.0) * x
        p = _sigmoid(z)
        # Preserve the hard blocker invariant even when the head is confident.
        if float(s.get("validator_pass", 1.0)) < 0.5:
            p = min(p, self.blocker_cap)
        return _clip(p)


def _load_learned_combiner() -> "LearnedCombiner | None":
    """Load the trained calibration head from ``SOWSMITH_CALIBRATION_HEAD`` (a
    JSON path), or None to fall back to the hand-tuned combiner."""
    import os

    path = os.environ.get("SOWSMITH_CALIBRATION_HEAD")
    if not path or not os.path.isfile(path):
        return None
    try:
        return LearnedCombiner.from_json(path)
    except Exception:
        return None


@dataclass
class CalibrationModel:
    """Linear combiner + optional :class:`PlattCalibrator`.

    When a trained :class:`LearnedCombiner` is configured (env
    ``SOWSMITH_CALIBRATION_HEAD``), it supersedes the hand-tuned combiner for
    the P(accept) estimate; otherwise the hand-tuned path runs unchanged.
    """

    weights: SignalWeights = field(default_factory=SignalWeights)
    platt: PlattCalibrator = field(default_factory=PlattCalibrator)
    blocker_cap: float = 0.20
    warning_cap: float = 0.80
    learned: "LearnedCombiner | None" = field(default_factory=_load_learned_combiner)

    def raw_score(self, sig: SignalVector) -> float:
        w = self.weights
        score = (
            w.parser_confidence * sig.parser_confidence
            + w.graph_confidence * sig.graph_confidence
            + w.packet_confidence * sig.packet_confidence
            + w.claim_confidence * sig.claim_confidence
            + w.contradiction_density * sig.contradiction_density
            + w.retrieval_coverage * sig.retrieval_coverage
            + w.ambiguity_penalty * (1.0 - sig.ambiguity)
            + w.example_similarity * sig.example_similarity
            + w.validator_pass * sig.validator_pass
            + w.validator_warning_penalty * (1.0 - sig.validator_warning)
        )
        # Hard caps from validator state.
        if sig.validator_pass < 0.5:
            score = min(score, self.blocker_cap)
        if sig.validator_warning > 0.5:
            score = min(score, self.warning_cap)
        return _clip(score)

    def calibrated(self, sig: SignalVector) -> float:
        # Trained head supersedes the hand-tuned combiner when configured.
        if self.learned is not None:
            return self.learned.prob(sig)
        return _clip(self.platt.predict(self.raw_score(sig)))

    def fit_platt(
        self, signals: Iterable[SignalVector], labels: Iterable[int]
    ) -> None:
        """Re-fit the Platt sigmoid against (signal, label) pairs."""
        raw_scores = [self.raw_score(s) for s in signals]
        self.platt.fit(raw_scores, list(labels))


# ────────────────────────────── helpers ────────────────────────────────


def _clip(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    ez = math.exp(z)
    return ez / (1.0 + ez)
