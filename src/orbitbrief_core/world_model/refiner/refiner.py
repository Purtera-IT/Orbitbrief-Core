"""The deterministic refiner pass."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from orbitbrief_core.evidence_runtime.runtime import EvidenceRuntime, RuntimeKey
from orbitbrief_core.world_model.pack_prior.state import PackPriorState
from orbitbrief_core.world_model.planner.schema import (
    BriefState,
    Claim,
    PackActivation,
    ReviewFlag,
    ReviewFlagCategory,
    ReviewFlagSeverity,
    SiteSummary,
)
from orbitbrief_core.world_model.registry import (
    DomainPackRegistry,
    load_default_registry,
)
from orbitbrief_core.world_model.site_reality.state import SiteRealityState


@dataclass(frozen=True)
class RefinementResult:
    """Refined :class:`BriefState` plus a structured changelog."""

    state: BriefState
    dropped_claims: tuple[dict[str, Any], ...]
    dropped_pack_activations: tuple[str, ...]
    dropped_sites: tuple[str, ...]
    duplicate_claims_collapsed: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "dropped_claims": list(self.dropped_claims),
            "dropped_pack_activations": list(self.dropped_pack_activations),
            "dropped_sites": list(self.dropped_sites),
            "duplicate_claims_collapsed": self.duplicate_claims_collapsed,
        }


def refine_brief(
    state: BriefState,
    *,
    runtime: EvidenceRuntime,
    pack_prior: PackPriorState,
    site_reality: SiteRealityState,
    registry: DomainPackRegistry | None = None,
    key: RuntimeKey | None = None,
) -> RefinementResult:
    """Apply graph-consistency rules to ``state`` and return the refined version."""
    rk = key or runtime.default_key
    if rk is None:
        raise ValueError("refine_brief: runtime has no default key")
    reg = registry or load_default_registry()

    # 1. Build the lookup sets we'll validate against.
    valid_atom_ids: set[str] = {
        a["id"]
        for a in (runtime.to_envelope_dict(rk).get("atoms") or ())
        if a.get("id")
    }
    active_pack_ids = {a.pack_id for a in state.pack_activations}
    valid_cluster_ids = {c.cluster_id for c in site_reality.clusters}
    valid_pack_ids = set(reg.all_ids())

    dropped_claims: list[dict[str, Any]] = []
    dropped_packs: list[str] = []
    dropped_sites: list[str] = []
    dup_collapsed = 0

    # 2. Filter pack_activations to known packs.
    kept_activations: list[PackActivation] = []
    for pa in state.pack_activations:
        if pa.pack_id not in valid_pack_ids:
            dropped_packs.append(pa.pack_id)
            continue
        kept_activations.append(pa)
    surviving_pack_ids = {pa.pack_id for pa in kept_activations}

    # 3. Filter sites to known clusters.
    kept_sites: list[SiteSummary] = []
    for s in state.sites:
        if s.cluster_id not in valid_cluster_ids:
            dropped_sites.append(s.cluster_id)
            continue
        kept_sites.append(s)

    # 4. Filter + dedupe claims.
    seen_keys: set[tuple[str, tuple[str, ...]]] = set()
    kept_claims: list[Claim] = []
    for c in state.claims:
        # 4a. Atom ids must all resolve in the runtime.
        unknown_atoms = [aid for aid in c.supporting_atom_ids if aid not in valid_atom_ids]
        if unknown_atoms:
            dropped_claims.append(
                {
                    "claim_id": c.id,
                    "reason": "unknown_atom_ids",
                    "unknown_atom_ids": unknown_atoms,
                }
            )
            continue
        # 4b. pack_id (if any) must be in the surviving activation set.
        if c.pack_id is not None and c.pack_id not in surviving_pack_ids:
            dropped_claims.append(
                {
                    "claim_id": c.id,
                    "reason": "unknown_pack_id",
                    "pack_id": c.pack_id,
                }
            )
            continue
        # 4c. Dedupe on (statement, sorted-atoms).
        key_tuple = (c.statement.strip().lower(), tuple(sorted(c.supporting_atom_ids)))
        if key_tuple in seen_keys:
            dup_collapsed += 1
            continue
        seen_keys.add(key_tuple)
        kept_claims.append(c)

    # 5. Add INFO review flags for dropped artifacts so reviewers
    #    see the cleanup that happened.
    new_flags: list[ReviewFlag] = list(state.review_flags)
    if dropped_claims:
        new_flags.append(
            ReviewFlag(
                severity=ReviewFlagSeverity.INFO,
                category=ReviewFlagCategory.AMBIGUITY,
                message=(
                    f"refiner dropped {len(dropped_claims)} claim(s) "
                    f"with unknown atom or pack ids"
                )[:400],
            )
        )
    if dropped_packs:
        new_flags.append(
            ReviewFlag(
                severity=ReviewFlagSeverity.INFO,
                category=ReviewFlagCategory.AMBIGUITY,
                message=(
                    f"refiner dropped {len(dropped_packs)} unknown pack id(s): "
                    f"{', '.join(dropped_packs)[:200]}"
                )[:400],
            )
        )
    if dropped_sites:
        new_flags.append(
            ReviewFlag(
                severity=ReviewFlagSeverity.INFO,
                category=ReviewFlagCategory.AMBIGUITY,
                message=(
                    f"refiner dropped {len(dropped_sites)} unknown cluster id(s): "
                    f"{', '.join(dropped_sites)[:200]}"
                )[:400],
            )
        )

    refined = state.model_copy(
        update={
            "pack_activations": tuple(kept_activations),
            "sites": tuple(kept_sites),
            "claims": tuple(kept_claims),
            "review_flags": tuple(new_flags),
            "escalation_log": {
                **state.escalation_log,
                "refiner": {
                    "dropped_claims": len(dropped_claims),
                    "dropped_pack_activations": len(dropped_packs),
                    "dropped_sites": len(dropped_sites),
                    "duplicate_claims_collapsed": dup_collapsed,
                },
            },
        }
    )
    return RefinementResult(
        state=refined,
        dropped_claims=tuple(dropped_claims),
        dropped_pack_activations=tuple(dropped_packs),
        dropped_sites=tuple(dropped_sites),
        duplicate_claims_collapsed=dup_collapsed,
    )
