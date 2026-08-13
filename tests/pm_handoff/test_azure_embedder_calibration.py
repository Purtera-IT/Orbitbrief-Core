"""Thresholds must track the embedder, and the swap must not silently kill dedupe.

Measured 2026-08-13 over 630 real question pairs from the Clayton brief under
Azure text-embedding-3-small:

  * highest cosine of ANY pair = 0.773, so the 0.82 gate merged NOTHING
  * the ranking INVERTS -- a false pair scores 0.773 while a true duplicate
    scores 0.760 -- so no cosine threshold separates them
  * containment separates them cleanly: 0.400 (false) vs 0.875 (true)

The neural path hardcoded containment >= 0.92, which misses the true duplicate
at 0.875. These lock in the calibration that actually works.
"""
from __future__ import annotations

from orbitbrief_core.pm_handoff.semantic_dedupe import (
    AzureOpenAIEmbedder,
    pair_near_duplicate,
    resolve_question_embedder,
    soft_containment,
)

TRUE_A = "Confirm site access, escort, and badging requirements for Clayton Homes Maryville"
TRUE_B = "Confirm access/escort/badging/after-hours requirements for Clayton Homes Maryville"
FALSE_A = "Who is the day-of onsite contact for Clayton Rd Maryville TN"


def _vec(cos_to_other: float):
    """Two unit vectors with a known cosine, so we test the GATE not the model."""
    import math

    return [1.0, 0.0], [cos_to_other, math.sqrt(max(0.0, 1 - cos_to_other**2))]


def test_containment_separates_what_cosine_cannot():
    assert soft_containment(TRUE_A, TRUE_B) > 0.85
    assert soft_containment(FALSE_A, TRUE_B) < 0.60


def test_true_duplicate_merges_at_calibrated_containment():
    a, b = _vec(0.760)  # real measured cosine for this pair
    is_dup, cos, cont = pair_near_duplicate(
        TRUE_A, TRUE_B, a, b, cosine_threshold=0.78, neural_containment=0.85, neural=True
    )
    assert is_dup, f"true duplicate missed (cos={cos:.3f} cont={cont:.3f})"


def test_false_pair_does_not_merge_despite_higher_cosine():
    a, b = _vec(0.773)  # HIGHER cosine than the true duplicate above
    is_dup, cos, cont = pair_near_duplicate(
        FALSE_A, TRUE_B, a, b, cosine_threshold=0.78, neural_containment=0.85, neural=True
    )
    assert not is_dup, f"false pair merged (cos={cos:.3f} cont={cont:.3f})"


def test_old_hardcoded_gate_would_have_missed_the_duplicate():
    a, b = _vec(0.760)
    is_dup, _, _ = pair_near_duplicate(
        TRUE_A, TRUE_B, a, b, cosine_threshold=0.82, neural_containment=0.92, neural=True
    )
    assert not is_dup, "this documents the regression the calibration fixes"


def test_azure_is_preferred_when_configured(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://x.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "k")
    monkeypatch.setenv("AZURE_OPENAI_EMBED_DEPLOYMENT", "text-embedding-3-small")
    monkeypatch.setenv("OLLAMA_EMBED_URL", "https://mac.example/api/embed")
    emb = resolve_question_embedder()
    assert isinstance(emb, AzureOpenAIEmbedder), "Azure must win over the Mac"
    assert emb.dim == 1536


def test_falls_back_to_ollama_when_azure_absent(monkeypatch):
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OLLAMA_EMBED_URL", "https://mac.example/api/embed")
    emb = resolve_question_embedder()
    assert not isinstance(emb, AzureOpenAIEmbedder)
