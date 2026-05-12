"""Phase-2 perf gate: top-k over 10K packets ≤ 200 ms p95.

We synthesize 10K packet-shaped rows (real corpora at this scale
don't ship with the repo), embed them with the deterministic hash
embedder, and time 50 search calls. p95 must beat the spec
threshold.

The threshold is a *static* check on the substrate — DuckDB+vss
HNSW + a 128-dim hash embedder. Real production hits will use
4096-dim Qwen3 embeddings against the same substrate; that's a
different perf regime tracked separately when we wire vLLM.
"""
from __future__ import annotations

import os
import statistics
import time

import pytest

from orbitbrief_core.retrieval import (
    DeterministicHashEmbedder,
    RetrievalStore,
    RetrievalStoreConfig,
)
from orbitbrief_core.retrieval.base import INDEX_KIND_PACKET


# Tunable via env so a slow CI box can still pass — but the
# default is the spec value.
P95_THRESHOLD_MS = float(os.environ.get("ORBITBRIEF_RETRIEVAL_P95_MS", "200"))
SYNTHETIC_ROW_COUNT = int(os.environ.get("ORBITBRIEF_RETRIEVAL_PERF_N", "10000"))
SYNTHETIC_QUERY_COUNT = int(os.environ.get("ORBITBRIEF_RETRIEVAL_PERF_QS", "50"))


@pytest.mark.perf
def test_top_k_over_10k_packets_under_200ms_p95() -> None:
    """Build → search 10K rows; p95 latency ≤ ``P95_THRESHOLD_MS``."""
    dim = 128
    embedder = DeterministicHashEmbedder(dim=dim)
    store = RetrievalStore.connect(RetrievalStoreConfig(dim=dim))
    try:
        # Synthesize 10K rows. Each "packet" gets a deterministic
        # text projection so two runs of this test embed the same
        # bytes.
        rows: list[tuple[str, dict, list[float]]] = []
        texts = [
            f"scope_inclusion|device:dev_{i:05d}|"
            f"deploy {i % 7} cameras at site {chr(65 + (i % 26))}"
            for i in range(SYNTHETIC_ROW_COUNT)
        ]
        vectors = embedder.embed(texts)
        for i, vec in enumerate(vectors):
            rows.append(
                (
                    f"pkt_synth_{i:05d}",
                    {"family": "scope_inclusion", "anchor_key": f"device:dev_{i:05d}"},
                    vec,
                )
            )
        store.upsert(
            INDEX_KIND_PACKET,
            project_id="perf_synth",
            compile_id="perf_synth",
            rows=rows,
        )
        store.ensure_hnsw(INDEX_KIND_PACKET)

        # Time SYNTHETIC_QUERY_COUNT searches with deterministic
        # but varied queries.
        latencies_ms: list[float] = []
        for q in range(SYNTHETIC_QUERY_COUNT):
            qtext = f"deploy cameras at site {chr(65 + (q % 26))}"
            qvec = embedder.embed([qtext])[0]
            t0 = time.perf_counter()
            store.search(
                INDEX_KIND_PACKET,
                project_id="perf_synth",
                compile_id="perf_synth",
                query_vec=qvec,
                top_k=10,
            )
            latencies_ms.append((time.perf_counter() - t0) * 1000.0)

        latencies_ms.sort()
        p50 = latencies_ms[len(latencies_ms) // 2]
        p95 = latencies_ms[max(0, int(len(latencies_ms) * 0.95) - 1)]
        avg = statistics.fmean(latencies_ms)
        # Print so a passing run still surfaces the numbers.
        print(
            f"\nretrieval perf over {SYNTHETIC_ROW_COUNT} rows / "
            f"{SYNTHETIC_QUERY_COUNT} queries:\n"
            f"  avg={avg:.2f}ms  p50={p50:.2f}ms  p95={p95:.2f}ms  "
            f"(threshold={P95_THRESHOLD_MS:.0f}ms)"
        )
        assert p95 <= P95_THRESHOLD_MS, (
            f"top-k over {SYNTHETIC_ROW_COUNT} rows: p95={p95:.2f}ms "
            f"exceeds threshold {P95_THRESHOLD_MS:.2f}ms"
        )
    finally:
        store.close()
