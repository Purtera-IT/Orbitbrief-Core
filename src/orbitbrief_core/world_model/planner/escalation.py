"""Pre-call escalation rules: 14B (default) vs 32B (escalated).

The decision is made *before* any LLM call so we can honor the
"bounded LLM use" Phase-3/4 constraint and keep the cost
telemetry honest. Every rule that fires gets logged with a
structured reason so the corpus-wide escalation rate is auditable.

Rules (any one fires → escalate):

* ``contradiction_density`` — > 5 % of atoms are involved in a
  contradiction. The 14B model under-prioritizes contradiction
  reconciliation; 32B has more headroom.
* ``unstable_site_model`` — > 30 % of site clusters were
  resolved by the SiteRealityEngine's LLM path. That's a sign the
  graph is noisy; planning needs more capacity.
* ``pack_ambiguity`` — PackPriorState.margin < 0.10. Even tighter
  than pack_prior's own 0.15 escalation gate; we want 32B when
  the prior itself is shaky.
* ``sparse_but_material`` — atom_count < 20 yet at least one atom
  carries a contractual / customer-current authority class. Few
  but high-stakes atoms — small misreads have big consequences.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from orbitbrief_core.world_model.pack_prior.state import PackPriorState
from orbitbrief_core.world_model.site_reality.state import SiteRealityState


class PlannerTier(str, Enum):
    DEFAULT = "default"  # Qwen3-14B
    ESCALATED = "escalated"  # Qwen3-32B


class PlannerEscalationReason(str, Enum):
    CONTRADICTION_DENSITY = "contradiction_density"
    UNSTABLE_SITE_MODEL = "unstable_site_model"
    PACK_AMBIGUITY = "pack_ambiguity"
    SPARSE_BUT_MATERIAL = "sparse_but_material"


# Authority classes that count as "material" for the
# sparse_but_material rule. Pulled from parser-os schemas; keep
# in sync if the enum grows.
_MATERIAL_AUTHORITY: frozenset[str] = frozenset({
    "contractual_scope",
    "customer_current_authored",
    "approved_site_roster",
})


@dataclass(frozen=True)
class PlannerEscalation:
    """Result of running the escalation rules against the inputs."""

    tier: PlannerTier
    reasons: tuple[PlannerEscalationReason, ...] = ()
    metrics: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier.value,
            "reasons": [r.value for r in self.reasons],
            "metrics": dict(self.metrics),
        }


def decide_tier(
    *,
    pack_prior: PackPriorState,
    site_reality: SiteRealityState,
    envelope: dict[str, Any],
    contradiction_count: int,
    contradiction_density_threshold: float = 0.05,
    unstable_site_threshold: float = 0.30,
    pack_margin_threshold: float = 0.10,
    sparse_atom_threshold: int = 20,
) -> PlannerEscalation:
    """Apply the four escalation rules and return the verdict + metrics."""
    atoms = envelope.get("atoms") or ()
    atom_count = len(atoms)

    # contradiction density
    contradiction_density = (
        contradiction_count / atom_count if atom_count else 0.0
    )

    # unstable site model
    cluster_count = site_reality.cluster_count or 0
    site_log = site_reality.escalation_log or {}
    site_llm_calls = int(site_log.get("count", 0) or 0)
    unstable_ratio = (
        site_llm_calls / cluster_count if cluster_count else 0.0
    )

    # pack ambiguity (lower margin = more ambiguous)
    pack_margin = float(pack_prior.margin)

    # sparse-but-material
    has_material_authority = any(
        (a.get("authority_class") in _MATERIAL_AUTHORITY) for a in atoms
    )
    sparse_but_material = (
        atom_count < sparse_atom_threshold and has_material_authority
    )

    metrics = {
        "contradiction_density": contradiction_density,
        "unstable_site_ratio": unstable_ratio,
        "pack_margin": pack_margin,
        "atom_count": float(atom_count),
        "site_llm_calls": float(site_llm_calls),
    }

    reasons: list[PlannerEscalationReason] = []
    if contradiction_density > contradiction_density_threshold:
        reasons.append(PlannerEscalationReason.CONTRADICTION_DENSITY)
    if cluster_count > 0 and unstable_ratio > unstable_site_threshold:
        reasons.append(PlannerEscalationReason.UNSTABLE_SITE_MODEL)
    if pack_margin < pack_margin_threshold:
        reasons.append(PlannerEscalationReason.PACK_AMBIGUITY)
    if sparse_but_material:
        reasons.append(PlannerEscalationReason.SPARSE_BUT_MATERIAL)

    tier = PlannerTier.ESCALATED if reasons else PlannerTier.DEFAULT
    return PlannerEscalation(tier=tier, reasons=tuple(reasons), metrics=metrics)
