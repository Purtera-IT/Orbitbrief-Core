"""Neural / embedding near-duplicate clustering for PM asks.

Used by the customer-question engine (and gap ↔ question cross-suppress)
so paraphrase duplicates collapse to one canonical ask — not brittle
string equality or deal-id hacks.

Production: prefers :class:`RemoteVllmEmbedder` when
``ORBITBRIEF_EMBED_BASE_URL`` (or ``VLLM_BASE_URL``) is set.
Offline / CI: :class:`DeterministicHashEmbedder` plus a soft
content-token containment check that catches subset paraphrases
(e.g. composite SOP+approval vs approval-only).
"""
from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, field
from typing import Callable, Protocol, Sequence, TypeVar

from orbitbrief_core.retrieval.embedder import DeterministicHashEmbedder, Embedder

# Cosine threshold for "same intent". Real Qwen embeddings cluster
# paraphrases higher; hash embedder is weaker so we also use containment.
DEFAULT_COSINE_THRESHOLD = float(os.environ.get("ORBITBRIEF_QUESTION_DEDUP_COSINE", "0.78"))
DEFAULT_CONTAINMENT_THRESHOLD = float(
    # 0.75 catches subset paraphrases under the hash embedder; real
    # Qwen embeddings still dominate via cosine when available.
    os.environ.get("ORBITBRIEF_QUESTION_DEDUP_CONTAINMENT", "0.75")
)
# When both signals are moderate, still merge (subset + lexical overlap).
DEFAULT_HYBRID_COSINE = float(os.environ.get("ORBITBRIEF_QUESTION_DEDUP_HYBRID_COSINE", "0.55"))
DEFAULT_HYBRID_CONTAINMENT = float(
    os.environ.get("ORBITBRIEF_QUESTION_DEDUP_HYBRID_CONTAINMENT", "0.60")
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    """
    a an the and or of to for on in at by with from is are was were be been being
    this that these those it its we our you your they their who what which when
    where how can could should would will may might do does did get got have has
    had please confirm determine request ask need needed before after also just
    """.split()
)

# Coarse intent families for offline (hash) embedder — both sides must hit
# ≥2 tokens in the same family before we treat them as the same ask.
# Remote Qwen embeddings still dominate when configured.
_INTENT_FAMILIES: tuple[frozenset[str], ...] = (
    frozenset(
        {
            "sop",
            "approv",
            "acceptance",
            "revision",
            "authority",
            "governance",
            "sign",
            "pass",
            "fail",
            "criteria",
            "poc",
        }
    ),
    frozenset({"topology", "hub", "spoke", "meraki", "edge", "device", "shared"}),
    frozenset({"circuit", "carrier", "demarc", "ready", "turn"}),
    frozenset({"montreal", "defer", "phase", "paper", "cdw", "canada"}),
    frozenset({"survey", "walkthrough", "first", "schedule", "access"}),
    frozenset({"smart", "remote", "hand", "rack", "stack", "config", "physical"}),
)

T = TypeVar("T")


class _SupportsText(Protocol):
    pass


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return float(sum(x * y for x, y in zip(a, b)))


def _stem_token(tok: str) -> str:
    """Light morphological fold so approve/approval/approves share a stem.

    Conservative suffixes only — enough for PM-ask paraphrases under the
    offline hash embedder. Remote Qwen embeddings do the heavy lifting
    in production when ``ORBITBRIEF_EMBED_BASE_URL`` is set.
    """
    t = tok
    if len(t) <= 3:
        return t
    if t.endswith("ies") and len(t) > 4:
        t = t[:-3] + "y"
    elif t.endswith(("sses", "ches", "shes", "xes", "zes")) and len(t) > 4:
        t = t[:-2]
    elif t.endswith("es") and len(t) > 4:
        t = t[:-2]
    elif t.endswith("s") and not t.endswith("ss") and len(t) > 3:
        t = t[:-1]
    if t.endswith("ing") and len(t) > 5:
        t = t[:-3]
    elif t.endswith("ed") and len(t) > 4:
        t = t[:-2]
    # approval → approv (pairs with approves→approv via -es rule above)
    if t.endswith("al") and len(t) > 5:
        t = t[:-2]
    return t


def content_tokens(text: str) -> frozenset[str]:
    """Intent-bearing tokens (stopwords stripped, lightly stemmed)."""
    return frozenset(
        _stem_token(t)
        for t in _TOKEN_RE.findall((text or "").lower())
        if t not in _STOP and len(t) > 2
    )


def soft_containment(a: str, b: str) -> float:
    """Fraction of the smaller token set covered by the larger.

    Catches subset paraphrases where one ask is folded into another
    (e.g. approval-only ⊂ SOP + approval composite).
    """
    A, B = content_tokens(a), content_tokens(b)
    if not A or not B:
        return 0.0
    inter = len(A & B)
    return inter / float(min(len(A), len(B)))


def shared_intent_family(text_a: str, text_b: str, *, min_hits: int = 2) -> bool:
    """True when both texts hit the same intent family with ≥min_hits tokens each."""
    ta, tb = content_tokens(text_a), content_tokens(text_b)
    for family in _INTENT_FAMILIES:
        if len(ta & family) >= min_hits and len(tb & family) >= min_hits:
            return True
    return False


def is_neural_embedder(embedder: Embedder | None) -> bool:
    """True when using a remote neural embedder (not the offline hash stub)."""
    if embedder is None:
        return False
    mid = str(getattr(embedder, "model_id", "") or "").lower()
    return bool(mid) and "deterministic-hash" not in mid


def pair_near_duplicate(
    text_a: str,
    text_b: str,
    vec_a: Sequence[float],
    vec_b: Sequence[float],
    *,
    cosine_threshold: float = DEFAULT_COSINE_THRESHOLD,
    containment_threshold: float = DEFAULT_CONTAINMENT_THRESHOLD,
    hybrid_cosine: float = DEFAULT_HYBRID_COSINE,
    hybrid_containment: float = DEFAULT_HYBRID_CONTAINMENT,
    neural: bool = False,
) -> tuple[bool, float, float]:
    """Return (is_dup, cosine, containment).

    Neural path: cosine only (plus near-exact containment ≥0.92). Intent-family
    and soft lexical gates over-merged SOP vs approval on live deals — disabled
    when Qwen embeddings are available.
    """
    cos = cosine_similarity(vec_a, vec_b)
    cont = soft_containment(text_a, text_b)
    if neural:
        is_dup = cos >= cosine_threshold or cont >= 0.92
        return is_dup, cos, cont
    is_dup = (
        cos >= cosine_threshold
        or cont >= containment_threshold
        or (cos >= hybrid_cosine and cont >= hybrid_containment)
        or shared_intent_family(text_a, text_b)
    )
    return is_dup, cos, cont


def evidence_relevance_scores(
    questions: Sequence[str],
    evidence_blob: str,
    *,
    embedder: Embedder | None = None,
) -> tuple[list[float], str]:
    """Cosine relevance of each question to the deal evidence (neural when live)."""
    emb = resolve_question_embedder(embedder)
    if not questions:
        return [], emb.model_id
    blob = re.sub(r"\s+", " ", (evidence_blob or "").strip())[:4500]
    query = (
        "Unresolved project-manager decisions that must be answered before quoting "
        "and scheduling this engagement. Prefer concrete deal-specific asks grounded "
        "in the evidence below; demote generic checklists, smalltalk, and misframed "
        "governance.\n\nEvidence:\n"
        f"{blob}"
    )
    try:
        vecs = emb.embed([query, *[q or "" for q in questions]])
    except Exception:
        emb = DeterministicHashEmbedder(dim=256)
        vecs = emb.embed([query, *[q or "" for q in questions]])
    qv = vecs[0]
    scores = [cosine_similarity(qv, vecs[i + 1]) for i in range(len(questions))]
    return scores, emb.model_id


@dataclass
class ClusterMeta:
    """Debug / metrics for one dedupe pass."""

    input_count: int
    output_count: int
    cluster_count: int
    merged_pairs: int
    embedder_model: str
    cosine_threshold: float
    containment_threshold: float


def _l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    if norm <= 0:
        return vec
    return [x / norm for x in vec]


@dataclass
class OllamaHttpEmbedder:
    """Ollama ``/api/embed`` (batch) or ``/api/embeddings`` (single) client."""

    base_url: str  # host root or full …/api/embed URL
    model_id: str
    dim: int = 4096
    api_key: str = ""
    _cache: dict[str, list[float]] = field(default_factory=dict, repr=False)

    def embed(self, texts: list[str]) -> list[list[float]]:
        import json
        import urllib.request

        if not texts:
            return []
        out: list[list[float] | None] = [None] * len(texts)
        miss: list[tuple[int, str]] = []
        for i, t in enumerate(texts):
            cached = self._cache.get(t)
            if cached is not None:
                out[i] = cached
            else:
                miss.append((i, t))
        if not miss:
            return [v for v in out if v is not None]

        root = self.base_url.rstrip("/")
        if root.endswith("/api/embed"):
            embed_url = root
        elif root.endswith("/api/embeddings"):
            embed_url = root[: -len("/embeddings")] + "/embed"
        else:
            embed_url = root + "/api/embed"

        payload = json.dumps({"model": self.model_id, "input": [t for _, t in miss]}).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            # Some edge proxies 403 bare urllib user-agents.
            "User-Agent": "orbitbrief-core-question-dedupe/1.0",
            "Accept": "application/json",
        }
        if self.api_key:
            token = self.api_key.strip()
            headers["Authorization"] = f"Bearer {token}"
            # Some gateways expect the raw token without the Bearer prefix.
            headers["X-Api-Key"] = token

        def _post(url: str, body: bytes, hdr: dict[str, str]) -> dict:
            req = urllib.request.Request(url, data=body, headers=hdr, method="POST")
            with urllib.request.urlopen(req, timeout=90) as resp:
                return json.loads(resp.read().decode("utf-8"))

        fresh: list[list[float]] = []
        try:
            data = _post(embed_url, payload, headers)
            raw = data.get("embeddings") or []
            fresh = [_l2_normalize([float(x) for x in row]) for row in raw]
        except Exception:
            # Fall back to per-prompt /api/embeddings
            emb_url = embed_url.rsplit("/", 1)[0] + "/embeddings"
            header_variants = [headers]
            # Retry without Authorization (some reverse proxies reject it)
            bare = {
                "Content-Type": "application/json",
                "User-Agent": headers["User-Agent"],
                "Accept": "application/json",
            }
            if self.api_key:
                header_variants.append({**bare, "Authorization": f"Bearer {self.api_key.strip()}"})
            header_variants.append(bare)
            last_err: Exception | None = None
            for hdr in header_variants:
                try:
                    batch: list[list[float]] = []
                    for _, t in miss:
                        p = json.dumps({"model": self.model_id, "prompt": t}).encode("utf-8")
                        one = _post(emb_url, p, hdr)
                        vec = one.get("embedding") or []
                        batch.append(_l2_normalize([float(x) for x in vec]))
                    fresh = batch
                    last_err = None
                    break
                except Exception as e:
                    last_err = e
                    fresh = []
            if last_err is not None and len(fresh) != len(miss):
                # Never kill PM handoff when the embed proxy flaps (e.g. HTTP 530).
                # Hash vectors keep dedupe/fact-quality functional in degraded mode.
                import logging

                logging.getLogger(__name__).warning(
                    "ollama embed unavailable (%s); falling back to deterministic-hash",
                    last_err,
                )
                hash_emb = DeterministicHashEmbedder(dim=256)
                fresh = hash_emb.embed([t for _, t in miss])
                self.model_id = "deterministic-hash-v1"
                self.dim = 256

        if len(fresh) != len(miss):
            hash_emb = DeterministicHashEmbedder(dim=256)
            fresh = hash_emb.embed([t for _, t in miss])
            self.model_id = "deterministic-hash-v1"
            self.dim = 256
        for (i, t), vec in zip(miss, fresh):
            if self.dim and len(vec) != self.dim:
                self.dim = len(vec)
            self._cache[t] = vec
            out[i] = vec
        return [v for v in out if v is not None]


def resolve_question_embedder(embedder: Embedder | None = None) -> Embedder:
    """Prefer Ollama/vLLM embeddings when configured; else deterministic hash."""
    if embedder is not None:
        return embedder

    # 1) Ollama (PurPulse host) — real neural near-dup for PM asks
    ollama_url = (
        os.environ.get("ORBITBRIEF_OLLAMA_EMBED_URL", "").strip()
        or os.environ.get("OLLAMA_EMBED_URL", "").strip()
        or os.environ.get("OLLAMA_HOST", "").strip()
    )
    ollama_model = (
        os.environ.get("ORBITBRIEF_OLLAMA_EMBED_MODEL", "").strip()
        or os.environ.get("OLLAMA_EMBED_MODEL", "").strip()
        or "qwen3-embedding:8b"
    )
    ollama_token = (
        os.environ.get("ORBITBRIEF_OLLAMA_EMBED_TOKEN", "").strip()
        or os.environ.get("OLLAMA_EMBED_AUTH_TOKEN", "").strip()
    )
    if ollama_url:
        try:
            return OllamaHttpEmbedder(
                base_url=ollama_url,
                model_id=ollama_model,
                api_key=ollama_token,
                dim=4096,
            )
        except Exception:
            pass

    # 2) OpenAI-compatible vLLM /v1/embeddings
    base = (
        os.environ.get("ORBITBRIEF_EMBED_BASE_URL", "").strip()
        or os.environ.get("VLLM_BASE_URL", "").strip()
        or os.environ.get("ORBITBRIEF_VLLM_BASE_URL", "").strip()
    )
    model = (
        os.environ.get("ORBITBRIEF_EMBED_MODEL", "").strip()
        or os.environ.get("VLLM_EMBED_MODEL", "").strip()
        or "Qwen/Qwen3-Embedding-8B"
    )
    dim_raw = os.environ.get("ORBITBRIEF_EMBED_DIM", "").strip()
    dim = int(dim_raw) if dim_raw.isdigit() else 4096
    if base:
        try:
            from orbitbrief_core.inference.client import VllmInferenceClient
            from orbitbrief_core.retrieval.embedder import RemoteVllmEmbedder

            client = VllmInferenceClient(base_url=base)
            return RemoteVllmEmbedder(client=client, model_id=model, dim=dim)
        except Exception:
            # Never fail the handoff build because embeddings are down.
            pass
    return DeterministicHashEmbedder(dim=256)


def _union_find_clusters(n: int, edges: list[tuple[int, int]]) -> list[list[int]]:
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    for i, j in edges:
        union(i, j)
    buckets: dict[int, list[int]] = {}
    for i in range(n):
        buckets.setdefault(find(i), []).append(i)
    return list(buckets.values())


def cluster_near_duplicates(
    texts: Sequence[str],
    *,
    embedder: Embedder | None = None,
    cosine_threshold: float = DEFAULT_COSINE_THRESHOLD,
    containment_threshold: float = DEFAULT_CONTAINMENT_THRESHOLD,
    hybrid_cosine: float = DEFAULT_HYBRID_COSINE,
    hybrid_containment: float = DEFAULT_HYBRID_CONTAINMENT,
) -> tuple[list[list[int]], ClusterMeta]:
    """Cluster indices of near-duplicate texts. Singleton clusters included."""
    n = len(texts)
    emb = resolve_question_embedder(embedder)
    if n == 0:
        return [], ClusterMeta(0, 0, 0, 0, emb.model_id, cosine_threshold, containment_threshold)
    try:
        vecs = emb.embed([t or "" for t in texts])
    except Exception:
        # Remote embed down → hash embedder so handoff still builds.
        emb = DeterministicHashEmbedder(dim=256)
        vecs = emb.embed([t or "" for t in texts])
    neural = is_neural_embedder(emb)
    # Neural paraphrases cluster tighter — raise bar so SOP ≠ approval.
    cos_thr = max(cosine_threshold, 0.80) if neural else cosine_threshold
    edges: list[tuple[int, int]] = []
    merged = 0
    for i in range(n):
        for j in range(i + 1, n):
            is_dup, _, _ = pair_near_duplicate(
                texts[i],
                texts[j],
                vecs[i],
                vecs[j],
                cosine_threshold=cos_thr,
                containment_threshold=containment_threshold,
                hybrid_cosine=hybrid_cosine,
                hybrid_containment=hybrid_containment,
                neural=neural,
            )
            if is_dup:
                edges.append((i, j))
                merged += 1
    clusters = _union_find_clusters(n, edges)
    meta = ClusterMeta(
        input_count=n,
        output_count=len(clusters),
        cluster_count=len(clusters),
        merged_pairs=merged,
        embedder_model=emb.model_id,
        cosine_threshold=cos_thr,
        containment_threshold=containment_threshold if not neural else 0.92,
    )
    return clusters, meta


def pick_best_index(
    indices: Sequence[int],
    *,
    score_fn: Callable[[int], tuple],
) -> int:
    """Highest score wins (tuple compared lexicographically, higher better)."""
    best = indices[0]
    best_s = score_fn(best)
    for i in indices[1:]:
        s = score_fn(i)
        if s > best_s:
            best, best_s = i, s
    return best


def semantic_dedupe(
    items: Sequence[T],
    *,
    text_fn: Callable[[T], str],
    score_fn: Callable[[T], tuple],
    embedder: Embedder | None = None,
    cosine_threshold: float = DEFAULT_COSINE_THRESHOLD,
    containment_threshold: float = DEFAULT_CONTAINMENT_THRESHOLD,
) -> tuple[list[T], ClusterMeta]:
    """Keep one best item per near-duplicate cluster. Order follows first-seen cluster winners."""
    texts = [text_fn(it) for it in items]
    clusters, meta = cluster_near_duplicates(
        texts,
        embedder=embedder,
        cosine_threshold=cosine_threshold,
        containment_threshold=containment_threshold,
    )
    kept: list[T] = []
    for group in clusters:
        winner = pick_best_index(group, score_fn=lambda i: score_fn(items[i]))
        kept.append(items[winner])
    meta = ClusterMeta(
        input_count=meta.input_count,
        output_count=len(kept),
        cluster_count=meta.cluster_count,
        merged_pairs=meta.merged_pairs,
        embedder_model=meta.embedder_model,
        cosine_threshold=meta.cosine_threshold,
        containment_threshold=meta.containment_threshold,
    )
    return kept, meta


def is_near_duplicate_of_any(
    text: str,
    others: Sequence[str],
    *,
    embedder: Embedder | None = None,
    cosine_threshold: float = DEFAULT_COSINE_THRESHOLD,
    containment_threshold: float = DEFAULT_CONTAINMENT_THRESHOLD,
) -> bool:
    """True if ``text`` is a near-dup of any string in ``others``."""
    if not text or not others:
        return False
    emb = resolve_question_embedder(embedder)
    corpus = [text, *[o for o in others if o]]
    if len(corpus) < 2:
        return False
    try:
        vecs = emb.embed(corpus)
    except Exception:
        emb = DeterministicHashEmbedder(dim=256)
        vecs = emb.embed(corpus)
    neural = is_neural_embedder(emb)
    cos_thr = max(cosine_threshold, 0.80) if neural else cosine_threshold
    for i in range(1, len(corpus)):
        is_dup, _, _ = pair_near_duplicate(
            corpus[0],
            corpus[i],
            vecs[0],
            vecs[i],
            cosine_threshold=cos_thr,
            containment_threshold=containment_threshold,
            neural=neural,
        )
        if is_dup:
            return True
    return False

