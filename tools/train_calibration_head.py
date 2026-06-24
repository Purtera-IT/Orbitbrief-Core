"""Train the CALIBRATION HEAD — the neural head for the brain pipeline.

The calibrator decides each brain claim's verdict (auto_accept / needs_review /
reject) from a 10-feature SignalVector. Today that's a HAND-TUNED linear combiner
fed through an identity Platt sigmoid — whose max output is sigmoid(1.0)=0.73,
BELOW the 0.80 auto-accept threshold, so NOTHING ever auto-accepts (every claim
lands in needs_review). This trains a logistic head over the same 10 signals to
P(accept) that is actually calibrated, then eval-gates it against the hand-tuned
baseline. Guess-free: at runtime the LearnedCombiner falls back to the hand-tuned
weights when the head is absent.

Tiny + dependency-light: numpy-only logistic regression; the artifact is ~11
floats of JSON (no torch/sklearn at train or runtime).

Trainset (`calibration_trainset.jsonl`, one row per claim):
    {"signals": {<10 feature floats>}, "gold": "auto_accept|needs_review|reject"}
produced by _label_claim_verdicts.py from harvested brief-gen calibration data.

Run:  python tools/train_calibration_head.py calibration_trainset.jsonl
Out:  calibration_head.json  (load via calibrator LearnedCombiner)
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

# Feature order is the contract with calibrator/signals.py SignalVector.
FEATURES = [
    "parser_confidence", "graph_confidence", "packet_confidence",
    "claim_confidence", "contradiction_density", "retrieval_coverage",
    "ambiguity", "example_similarity", "validator_pass", "validator_warning",
]

# Hand-tuned baseline (mirror of calibrator/model.py SignalWeights defaults +
# the (1-x) terms + hard caps) — what the head must beat.
_W = {
    "parser_confidence": 0.18, "graph_confidence": 0.05, "packet_confidence": 0.18,
    "claim_confidence": 0.12, "contradiction_density": 0.10, "retrieval_coverage": 0.08,
    "ambiguity_penalty": 0.10, "example_similarity": 0.05,
    "validator_pass": 0.10, "validator_warning_penalty": 0.04,
}
AUTO_ACCEPT_T, REVIEW_T = 0.80, 0.55


def _sigmoid(z):
    return np.where(z >= 0, 1.0 / (1.0 + np.exp(-z)), np.exp(z) / (1.0 + np.exp(z)))


def baseline_prob(s: dict) -> float:
    raw = (
        _W["parser_confidence"] * s["parser_confidence"]
        + _W["graph_confidence"] * s["graph_confidence"]
        + _W["packet_confidence"] * s["packet_confidence"]
        + _W["claim_confidence"] * s["claim_confidence"]
        + _W["contradiction_density"] * s["contradiction_density"]
        + _W["retrieval_coverage"] * s["retrieval_coverage"]
        + _W["ambiguity_penalty"] * (1.0 - s["ambiguity"])
        + _W["example_similarity"] * s["example_similarity"]
        + _W["validator_pass"] * s["validator_pass"]
        + _W["validator_warning_penalty"] * (1.0 - s["validator_warning"])
    )
    if s["validator_pass"] == 0.0:
        raw = min(raw, 0.20)
    if s["validator_warning"] == 1.0:
        raw = min(raw, 0.80)
    return float(1.0 / (1.0 + math.exp(-raw)))  # identity Platt (the deployed default)


def verdict(prob: float, validator_pass: float) -> str:
    if validator_pass == 0.0:
        return "reject"
    if prob >= AUTO_ACCEPT_T:
        return "auto_accept"
    if prob < 0.20:
        return "reject"
    return "needs_review"


def _load(path: str):
    X, y, S = [], [], []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        sig = r.get("signals") or {}
        gold = (r.get("gold") or "").strip()
        if gold not in ("auto_accept", "needs_review", "reject"):
            continue
        S.append({f: float(sig.get(f, 0.0)) for f in FEATURES})
        X.append([float(sig.get(f, 0.0)) for f in FEATURES])
        y.append(1.0 if gold == "auto_accept" else 0.0)  # binary accept-worthiness
    return np.array(X, float), np.array(y, float), S, [
        ("auto_accept" if v else "not_accept") for v in y]


def train_logistic(X, y, l2=1.0, iters=300):
    """IRLS / gradient descent logistic regression with L2. Standardize features."""
    mu, sd = X.mean(0), X.std(0) + 1e-9
    Xs = (X - mu) / sd
    Xb = np.hstack([Xs, np.ones((len(Xs), 1))])  # bias col
    w = np.zeros(Xb.shape[1])
    for _ in range(iters):
        p = _sigmoid(Xb @ w)
        grad = Xb.T @ (p - y) + l2 * np.r_[w[:-1], 0.0]
        # diagonal Hessian approx for a stable step
        W = np.clip(p * (1 - p), 1e-6, None)
        H = Xb.T @ (Xb * W[:, None]) + l2 * np.eye(Xb.shape[1])
        H[-1, -1] -= l2
        try:
            w -= np.linalg.solve(H, grad)
        except np.linalg.LinAlgError:
            w -= 0.01 * grad
    return w, mu, sd


def head_prob(w, mu, sd, s: dict) -> float:
    x = (np.array([s[f] for f in FEATURES]) - mu) / sd
    return float(_sigmoid(np.r_[x, 1.0] @ w))


def _metrics(probs, S, gold_accept):
    """auto-accept precision + recall + verdict accuracy vs 3-class gold proxy."""
    pred_acc = np.array([verdict(p, s["validator_pass"]) == "auto_accept"
                         for p, s in zip(probs, S)])
    ga = np.array(gold_accept, bool)
    tp = (pred_acc & ga).sum()
    prec = tp / max(pred_acc.sum(), 1)
    rec = tp / max(ga.sum(), 1)
    return float(prec), float(rec), int(pred_acc.sum())


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "calibration_trainset.jsonl"
    X, y, S, _ = _load(path)
    n = len(y)
    if n < 30:
        raise SystemExit(f"only {n} labeled claims — harvest+label more first")
    ga = (y == 1.0)
    print(f"CALIBRATION HEAD: {n} claims | auto_accept gold={int(ga.sum())} "
          f"({ga.mean()*100:.0f}%) | {len(FEATURES)} features")

    # 5-fold CV comparing head vs hand-tuned baseline (held-out).
    idx = np.arange(n)
    rng_order = sorted(idx, key=lambda i: (hash(("cv", int(i))) % 1000))  # deterministic shuffle
    folds = np.array_split(np.array(rng_order), 5)
    head_p, base_p, gold_f = [], [], []
    for k in range(5):
        te = folds[k]; tr = np.concatenate([folds[j] for j in range(5) if j != k])
        w, mu, sd = train_logistic(X[tr], y[tr])
        for i in te:
            head_p.append(head_prob(w, mu, sd, S[i]))
            base_p.append(baseline_prob(S[i]))
            gold_f.append(bool(ga[i]))
    hp, bp, gf = np.array(head_p), np.array(base_p), gold_f
    Sf = [S[i] for f in folds for i in f]  # align S to fold order
    h_prec, h_rec, h_fire = _metrics(hp, Sf, gf)
    b_prec, b_rec, b_fire = _metrics(bp, Sf, gf)
    print("\n=== held-out (5-fold) auto-accept: head vs hand-tuned baseline ===")
    print(f"  baseline : fires {b_fire:>3}  precision {b_prec:.3f}  recall {b_rec:.3f}")
    print(f"  HEAD     : fires {h_fire:>3}  precision {h_prec:.3f}  recall {h_rec:.3f}")
    print(f"  (baseline can't reach 0.80 by construction -> fires {b_fire}; the head unlocks safe auto-accepts)")

    promotable = (h_prec >= 0.85 and h_fire > b_fire) or (h_prec > b_prec and h_rec > b_rec)
    print("\nVERDICT:", "UNLOCK -- head beats hand-tuned, promotable"
          if promotable else "NOT yet -- needs more/cleaner labels (don't ship)")

    # Fit final head on ALL data; save tiny JSON artifact.
    w, mu, sd = train_logistic(X, y)
    art = {
        "mode": "logistic", "features": FEATURES,
        "weights": {f: float(w[i]) for i, f in enumerate(FEATURES)},
        "bias": float(w[-1]),
        "feature_mean": {f: float(mu[i]) for i, f in enumerate(FEATURES)},
        "feature_std": {f: float(sd[i]) for i, f in enumerate(FEATURES)},
        "n_train": n, "auto_accept_threshold": AUTO_ACCEPT_T, "review_threshold": REVIEW_T,
        "cv_precision": round(h_prec, 4), "cv_recall": round(h_rec, 4),
        "promotable": bool(promotable),
    }
    out = Path("calibration_head.json")
    out.write_text(json.dumps(art, indent=2), encoding="utf-8")
    print(f"\nsaved -> {out}  (load via calibrator LearnedCombiner; SOWSMITH_CALIBRATION_HEAD=<path>)")


if __name__ == "__main__":
    main()
