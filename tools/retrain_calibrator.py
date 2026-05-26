"""Nightly Platt-calibrator retrain.

Reads every ``TrainingRecord`` from ``$ORBITBRIEF_TRAINING_LOG`` (or
the path passed via ``--training-log``), fits the Platt sigmoid via
Newton-Raphson, and writes the new ``(a, b)`` parameters to a JSON
file that the orchestrator picks up on next compile.

Activation gate
---------------

* Below 50 records → script exits 0 with a message; does not write.
* 50 ≤ N < 500 → fits with a warning that the fit is preliminary.
* ≥ 500 → fits cleanly; treats the new params as production-ready.

Usage::

    python tools/retrain_calibrator.py \\
        --training-log /azure/blob/training_log.jsonl \\
        --out /azure/blob/platt_params.json

    # Or via env:
    export ORBITBRIEF_TRAINING_LOG=/abs/path/training_log.jsonl
    export ORBITBRIEF_PLATT_PARAMS=/abs/path/platt_params.json
    python tools/retrain_calibrator.py

Output ``platt_params.json`` shape::

    {
      "a":            1.42,
      "b":           -0.18,
      "n_records":   523,
      "n_accepted":  287,
      "n_rejected":  236,
      "ece":         0.038,        // expected calibration error
      "fit_at":      "2026-05-21T03:32:27.983Z",
      "model_version": "platt-v1"
    }

The orchestrator reads ``platt_params.json`` on startup and seeds
``CombinedCalibrator.platt`` with these values. Hot-swap safe — no
restart needed.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from orbitbrief_core.calibrator.model import PlattCalibrator  # noqa: E402
from orbitbrief_core.review_runtime.training_log import (  # noqa: E402
    JsonlTrainingLog,
)


MIN_RECORDS_TO_FIT = 50
MIN_RECORDS_FOR_PRODUCTION = 500
EXPECTED_BUCKETS = 10                                # for ECE binning


def compute_ece(
    raw_scores: list[float],
    labels: list[int],
    platt: PlattCalibrator,
    *,
    n_bins: int = EXPECTED_BUCKETS,
) -> float:
    """Expected calibration error in 10 buckets."""
    if not raw_scores:
        return 0.0
    predictions = [platt.predict(s) for s in raw_scores]
    paired = sorted(zip(predictions, labels))
    n = len(paired)
    bucket_size = max(1, n // n_bins)
    total_err = 0.0
    for i in range(0, n, bucket_size):
        bucket = paired[i : i + bucket_size]
        if not bucket:
            continue
        avg_pred = sum(p for p, _ in bucket) / len(bucket)
        avg_label = sum(y for _, y in bucket) / len(bucket)
        total_err += abs(avg_pred - avg_label) * (len(bucket) / n)
    return total_err


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--training-log",
        default=os.environ.get("ORBITBRIEF_TRAINING_LOG", "training_log.jsonl"),
        help="Path to JsonlTrainingLog (default: $ORBITBRIEF_TRAINING_LOG)",
    )
    p.add_argument(
        "--out",
        default=os.environ.get("ORBITBRIEF_PLATT_PARAMS", "platt_params.json"),
        help="Where to write fitted (a, b) params (default: $ORBITBRIEF_PLATT_PARAMS)",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Fit even when below MIN_RECORDS_TO_FIT (50). Useful for testing.",
    )
    args = p.parse_args(argv)

    training_log_path = Path(args.training_log).expanduser().resolve()
    if not training_log_path.exists():
        print(f"[retrain_calibrator] no training log at {training_log_path} — nothing to fit", flush=True)
        return 0

    log = JsonlTrainingLog(path=training_log_path)
    records = log.all()
    n = len(records)
    if n == 0:
        print("[retrain_calibrator] training log is empty — nothing to fit", flush=True)
        return 0

    if n < MIN_RECORDS_TO_FIT and not args.force:
        print(
            f"[retrain_calibrator] {n} records < {MIN_RECORDS_TO_FIT} threshold; "
            f"keeping existing calibrator. Pass --force to fit anyway.",
            flush=True,
        )
        return 0

    raw_scores = [float(r.predicted_raw_confidence) for r in records]
    labels = [1 if r.accepted else 0 for r in records]
    n_accepted = sum(labels)
    n_rejected = n - n_accepted

    platt = PlattCalibrator()
    platt.fit(raw_scores, labels)
    ece = compute_ece(raw_scores, labels, platt)

    out_path = Path(args.out).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "a": platt.a,
        "b": platt.b,
        "n_records": n,
        "n_accepted": n_accepted,
        "n_rejected": n_rejected,
        "ece": round(ece, 4),
        "fit_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "model_version": "platt-v1",
        "preliminary": n < MIN_RECORDS_FOR_PRODUCTION,
    }
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(
        f"[retrain_calibrator] fit {n} records "
        f"({n_accepted} accepted / {n_rejected} rejected) "
        f"→ a={platt.a:.3f} b={platt.b:.3f} ece={ece:.4f}"
        f"{' (preliminary)' if payload['preliminary'] else ''}",
        flush=True,
    )
    print(f"[retrain_calibrator] wrote {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
