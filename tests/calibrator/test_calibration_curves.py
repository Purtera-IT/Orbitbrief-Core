"""ECE ≤ 0.05 on a labeled set after Platt fitting.

Phase-6 verify gate.

Synthetic dataset
-----------------

We construct 500 (signal_vector, label) pairs whose true accept-
probability is a smooth function of three signals (parser, packet,
claim) plus noise. The :class:`CalibrationModel`'s linear combiner
gives us a raw score; :meth:`PlattCalibrator.fit` then learns a
sigmoid that maps raw → calibrated probability.

We split the dataset 70/30 into train/eval, fit on train, then
compute Expected Calibration Error (ECE) over 10 equal-width bins
on eval. A well-fit Platt sigmoid puts ECE under 0.05 — that's
the gate.
"""
from __future__ import annotations

import math
import random

import pytest

from orbitbrief_core.calibrator.model import (
    CalibrationModel,
    PlattCalibrator,
    SignalWeights,
)
from orbitbrief_core.calibrator.signals import SignalVector


N_SAMPLES = 1000
TRAIN_FRAC = 0.7
N_BINS = 10
ECE_GATE = 0.05
SEED = 12345


# For the calibration-curve test we use weights aligned to the
# synthetic data's true generator (parser=0.4, packet=0.4,
# claim=0.2, all others=0). This isolates the test from the
# production weight choice — we want to assert "Platt scaling
# recovers calibration on a well-ordered raw score", not "the
# default weights match this particular synthetic distribution".
TEST_WEIGHTS = SignalWeights(
    parser_confidence=0.4,
    graph_confidence=0.0,
    packet_confidence=0.4,
    claim_confidence=0.2,
    contradiction_density=0.0,
    retrieval_coverage=0.0,
    ambiguity_penalty=0.0,
    example_similarity=0.0,
    validator_pass=0.0,
    validator_warning_penalty=0.0,
)


def _true_prob(parser: float, packet: float, claim: float) -> float:
    """Smooth target: weighted average + sigmoid-shaped non-linearity."""
    raw = 0.4 * parser + 0.4 * packet + 0.2 * claim
    # Push the curve so ~half the samples sit near 0.5 (challenging for ECE).
    return 1.0 / (1.0 + math.exp(-(8 * (raw - 0.5))))


def _sample(rng: random.Random) -> tuple[SignalVector, int, float]:
    parser = rng.random()
    packet = rng.random()
    claim = rng.random()
    sig = SignalVector(
        parser_confidence=parser,
        graph_confidence=0.6,
        packet_confidence=packet,
        claim_confidence=claim,
        contradiction_density=0.8,
        retrieval_coverage=0.5,
        ambiguity=0.2,
        example_similarity=0.5,
        validator_pass=1.0,
        validator_warning=0.0,
    )
    p = _true_prob(parser, packet, claim)
    label = 1 if rng.random() < p else 0
    return sig, label, p


def _build_dataset(n: int = N_SAMPLES, *, seed: int = SEED):
    rng = random.Random(seed)
    return [_sample(rng) for _ in range(n)]


def _ece(probabilities: list[float], labels: list[int], *, n_bins: int = N_BINS) -> float:
    """Standard ECE with equal-width bins on [0, 1]."""
    bins: list[list[tuple[float, int]]] = [[] for _ in range(n_bins)]
    for p, y in zip(probabilities, labels):
        idx = min(int(p * n_bins), n_bins - 1)
        bins[idx].append((p, y))
    n = len(probabilities)
    if n == 0:
        return 0.0
    total = 0.0
    for bucket in bins:
        if not bucket:
            continue
        avg_p = sum(p for p, _ in bucket) / len(bucket)
        acc = sum(y for _, y in bucket) / len(bucket)
        total += (len(bucket) / n) * abs(avg_p - acc)
    return total


def test_calibrator_meets_ece_gate_after_platt_fit() -> None:
    """Linear combiner + fitted Platt sigmoid hits ECE ≤ 0.05 on held-out data."""
    dataset = _build_dataset()
    cut = int(len(dataset) * TRAIN_FRAC)
    train = dataset[:cut]
    eval_set = dataset[cut:]

    model = CalibrationModel(weights=TEST_WEIGHTS)
    model.fit_platt(
        signals=(s for s, _, _ in train),
        labels=(y for _, y, _ in train),
    )

    calibrated = [model.calibrated(s) for s, _, _ in eval_set]
    labels = [y for _, y, _ in eval_set]
    ece = _ece(calibrated, labels)
    assert ece <= ECE_GATE, (
        f"ECE {ece:.4f} above {ECE_GATE} gate "
        f"(eval n={len(eval_set)}, calibrated mean={sum(calibrated)/len(calibrated):.3f})"
    )


def test_validator_blocker_caps_score() -> None:
    """Even with maxed-out signals, a blocker caps raw at 0.20."""
    high = SignalVector(
        parser_confidence=1.0,
        graph_confidence=1.0,
        packet_confidence=1.0,
        claim_confidence=1.0,
        contradiction_density=1.0,
        retrieval_coverage=1.0,
        ambiguity=0.0,
        example_similarity=1.0,
        validator_pass=0.0,  # blocker
        validator_warning=0.0,
    )
    model = CalibrationModel()
    raw = model.raw_score(high)
    assert raw <= model.blocker_cap + 1e-9, raw


def test_validator_warning_caps_score() -> None:
    """With clean validator pass but a warning fired, raw caps at 0.80."""
    high_with_warning = SignalVector(
        parser_confidence=1.0,
        graph_confidence=1.0,
        packet_confidence=1.0,
        claim_confidence=1.0,
        contradiction_density=1.0,
        retrieval_coverage=1.0,
        ambiguity=0.0,
        example_similarity=1.0,
        validator_pass=1.0,
        validator_warning=1.0,
    )
    model = CalibrationModel()
    raw = model.raw_score(high_with_warning)
    assert raw <= model.warning_cap + 1e-9, raw


def test_platt_predict_clamped_to_unit_interval() -> None:
    """Sigmoid output is always in [0, 1] regardless of input magnitude."""
    pl = PlattCalibrator(a=10.0, b=-5.0)
    for x in (-100.0, 0.0, 0.5, 1.0, 100.0):
        p = pl.predict(x)
        assert 0.0 <= p <= 1.0, (x, p)
