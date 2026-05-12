"""Phase-2 quality smoke: 20-query golden retrieval, recall@10 ≥ 0.8.

The hash embedder is deliberately lexical, so we score it on a
golden set whose queries share tokens with their target docs.
That's enough to exercise the full pipeline end-to-end and prove
the substrate doesn't lose hits between embedder, store, and
search.

When a real Qwen3 embedder ships, this same harness will run
against semantic queries (paraphrases, synonyms) — the substrate
won't change.
"""
from __future__ import annotations

from dataclasses import dataclass

from orbitbrief_core.retrieval import (
    DeterministicHashEmbedder,
    RetrievalStore,
    RetrievalStoreConfig,
)
from orbitbrief_core.retrieval.base import INDEX_KIND_CLAIM


# 20 (query, expected_doc_id) pairs over a small synthetic corpus.
# Each query shares enough tokens with its target that any
# competent lexical embedder retrieves it inside top-10. Docs are
# disjoint enough that confounders don't drown out the target.
@dataclass(frozen=True)
class GoldenPair:
    query: str
    expected_id: str
    doc_text: str


GOLDEN_SET: list[GoldenPair] = [
    GoldenPair("how many cameras at building A",            "doc_001", "building A requires twelve outdoor cameras"),
    GoldenPair("night work allowed for site B",              "doc_002", "site B permits night work after 10 PM"),
    GoldenPair("excluded scope around fiber pathways",       "doc_003", "fiber pathway repairs are excluded from scope"),
    GoldenPair("conduit count for floor 3 risers",           "doc_004", "floor 3 risers need eight new conduits"),
    GoldenPair("WAP density requirement classroom",          "doc_005", "classrooms require one wireless access point per 30 students"),
    GoldenPair("badge access for vendors",                   "doc_006", "vendors need temporary badge access during install"),
    GoldenPair("UPS battery runtime spec",                   "doc_007", "UPS units must provide thirty minute battery runtime"),
    GoldenPair("low voltage cabling category 6A",            "doc_008", "all low voltage cabling shall be category 6A plenum"),
    GoldenPair("project closeout documentation deliverables","doc_009", "closeout documentation includes as-builts and warranty letters"),
    GoldenPair("contractor parking allocation",              "doc_010", "contractor parking is restricted to the south lot"),
    GoldenPair("paging speakers ceiling tile mount",         "doc_011", "ceiling paging speakers shall be tile-bridge mounted"),
    GoldenPair("CCTV recording retention 30 days",           "doc_012", "CCTV recordings must be retained for 30 days minimum"),
    GoldenPair("door hardware electric strike spec",         "doc_013", "electric strikes shall be 12VDC fail-secure"),
    GoldenPair("network switch PoE budget",                  "doc_014", "switches require PoE budget of 720 watts per chassis"),
    GoldenPair("fire alarm horn strobe coverage",            "doc_015", "horn strobes provide coverage in all corridors and rooms"),
    GoldenPair("equipment closet rack units capacity",       "doc_016", "each equipment closet provides forty two rack units"),
    GoldenPair("commissioning testing acceptance criteria",  "doc_017", "commissioning includes Cat 6A permanent link tests"),
    GoldenPair("emergency egress lighting battery",          "doc_018", "egress lighting must include 90 minute battery backup"),
    GoldenPair("HVAC integration BACnet protocol",           "doc_019", "HVAC controls integrate via BACnet IP gateway"),
    GoldenPair("structured cabling labeling scheme",         "doc_020", "structured cabling labels follow TIA-606-C convention"),
]


def test_golden_recall_at_10_meets_threshold() -> None:
    """Recall@10 over the 20-query golden set must clear 0.8."""
    dim = 128
    embedder = DeterministicHashEmbedder(dim=dim)
    store = RetrievalStore.connect(RetrievalStoreConfig(dim=dim))
    try:
        # Build a tiny claim-shaped index from the golden docs.
        # Use ClaimIndex's underlying store API directly so the
        # test doesn't depend on the runtime path (covered
        # elsewhere); we're isolating the embedder ↔ store ↔
        # search path here.
        rows = []
        for pair in GOLDEN_SET:
            (vec,) = embedder.embed([pair.doc_text])
            rows.append((pair.expected_id, {"text": pair.doc_text[:60]}, vec))
        store.upsert(
            INDEX_KIND_CLAIM,
            project_id="golden",
            compile_id="golden",
            rows=rows,
        )
        store.ensure_hnsw(INDEX_KIND_CLAIM)

        hits_in_top10 = 0
        misses: list[tuple[str, str, list[str]]] = []
        for pair in GOLDEN_SET:
            qvec = embedder.embed([pair.query])[0]
            results = store.search(
                INDEX_KIND_CLAIM,
                project_id="golden",
                compile_id="golden",
                query_vec=qvec,
                top_k=10,
            )
            ranked_ids = [r[0] for r in results]
            if pair.expected_id in ranked_ids:
                hits_in_top10 += 1
            else:
                misses.append((pair.query, pair.expected_id, ranked_ids))

        recall = hits_in_top10 / len(GOLDEN_SET)
        print(f"\nrecall@10 = {recall:.2f} ({hits_in_top10}/{len(GOLDEN_SET)})")
        assert recall >= 0.8, (
            f"recall@10 = {recall:.2f} < 0.8; misses:\n"
            + "\n".join(
                f"  q={q!r} expected={e} top10={ids[:5]}…"
                for q, e, ids in misses
            )
        )
    finally:
        store.close()
