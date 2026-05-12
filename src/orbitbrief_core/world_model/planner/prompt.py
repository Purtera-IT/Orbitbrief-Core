"""Build the LLM prompt that produces a :class:`BriefState`.

The prompt is purely a function of inputs — no I/O, no side
effects — so two runs over the same inputs produce identical
prompts and (with ``temperature=0``) identical outputs.

We feed the model:

* The pack-prior verdict (top packs + matched keywords) so it
  doesn't have to re-derive the routing.
* The site-reality clusters (id + canonical name + member atoms)
  so it can name dependencies precisely.
* A bounded retrieval bundle: top-K atoms per active pack, each
  with id, text snippet, authority class, confidence. The caller
  decides K to keep prompt size predictable.
* The contradictions detected by evidence_runtime, pre-formatted
  so the model only has to annotate (not invent) them.
* Active domain-pack priors (pack ids + display names + the
  workbook's subdomain labels) so the model knows what each pack
  cares about.

Hard rules baked into the system prompt:

* Output **must** be valid JSON conforming to the BriefState
  schema. No prose, no Markdown.
* Every claim **must** cite ``supporting_atom_ids`` from the
  retrieval bundle. Hallucinated atom ids are rejected by the
  refiner.
* No claim may exceed 500 chars; rationale 400 chars; flag
  message 400 chars (matches schema constraints — the LLM is
  told the limits up-front).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from orbitbrief_core.evidence_runtime.contradictions import ContradictionPair
from orbitbrief_core.inference.client import ChatMessage
from orbitbrief_core.world_model.pack_prior.state import PackPriorState
from orbitbrief_core.world_model.registry import DomainPack
from orbitbrief_core.world_model.site_reality.state import SiteRealityState


# We prune retrieval-bundle text to this many chars per atom so a
# noisy long atom can't blow out the prompt budget. The LLM still
# gets the atom id so it can refer back to it precisely.
_MAX_ATOM_CHARS = 280
# Top-K atoms per active pack in the bundle (caller may override).
_DEFAULT_TOP_K = 12


@dataclass(frozen=True)
class PlannerInputs:
    """Everything the prompt builder needs, gathered by :class:`Planner`."""

    project_id: str
    compile_id: str
    generated_at: str
    pack_prior: PackPriorState
    site_reality: SiteRealityState
    contradictions: tuple[ContradictionPair, ...]
    # Retrieval bundle: pack_id → list of compact atom dicts
    # (``id``, ``text``, ``authority_class``, ``confidence``).
    retrieval_bundles: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    # Active domain packs (typically the top-N from pack_prior the
    # caller decided are worth giving the LLM context for).
    active_packs: tuple[DomainPack, ...] = ()
    # Optional global atom budget across all active-pack bundles
    # combined. None disables the cap.
    max_total_atoms: int | None = None


@dataclass(frozen=True)
class PlannerPrompt:
    """The (system, user) message pair plus a debug snapshot."""

    system: str
    user: str
    snapshot: dict[str, Any]  # what the prompt builder packed in

    def messages(self) -> list[ChatMessage]:
        return [
            ChatMessage("system", self.system),
            ChatMessage("user", self.user),
        ]


def build_prompt(inputs: PlannerInputs, *, top_k_per_pack: int = _DEFAULT_TOP_K) -> PlannerPrompt:
    """Assemble system + user messages from runtime inputs."""
    system = _SYSTEM.strip()
    snapshot = _build_snapshot(inputs, top_k_per_pack=top_k_per_pack)
    user = _USER_TEMPLATE.format(
        project_id=inputs.project_id,
        compile_id=inputs.compile_id,
        generated_at=inputs.generated_at,
        snapshot_json=json.dumps(snapshot, indent=2, ensure_ascii=False),
    ).strip()
    return PlannerPrompt(system=system, user=user, snapshot=snapshot)


def _build_snapshot(inputs: PlannerInputs, *, top_k_per_pack: int) -> dict[str, Any]:
    # Pack-prior summary: top scores + their keyword matches.
    pp = inputs.pack_prior
    pack_summary = [
        {
            "pack_id": s.pack_id,
            "display_name": s.display_name,
            "raw_score": s.raw_score,
            "confidence": round(s.confidence, 4),
            "matched_keywords": list(s.matched_keywords)[:8],
        }
        for s in pp.scores[:8]
    ]
    pack_summary_top = {
        "top_pack_id": pp.top_pack_id,
        "runner_up_pack_id": pp.runner_up_pack_id,
        "margin": round(pp.margin, 4),
        "escalated": pp.escalated,
    }

    # Site clusters.
    sites = [
        {
            "cluster_id": c.cluster_id,
            "canonical_name": c.canonical_name,
            "candidate_names": list(c.candidate_names),
            "site_keys": list(c.site_keys),
            "member_atom_ids": list(c.member_atom_ids)[:20],
            "artifact_ids": list(c.artifact_ids),
            "confidence": round(c.confidence, 4),
        }
        for c in inputs.site_reality.clusters
    ]

    # Active pack docs.
    active_packs = [
        {
            "pack_id": p.id,
            "display_name": p.display_name,
            "subdomains": list(p.subdomain_labels),
        }
        for p in inputs.active_packs
    ]

    # Retrieval bundles, capped per pack and (optionally) total.
    bundles: dict[str, list[dict[str, Any]]] = {}
    total = 0
    for pack_id, atoms in inputs.retrieval_bundles.items():
        kept: list[dict[str, Any]] = []
        for atom in atoms[:top_k_per_pack]:
            if (
                inputs.max_total_atoms is not None
                and total >= inputs.max_total_atoms
            ):
                break
            kept.append(
                {
                    "atom_id": atom["id"],
                    "text": (atom.get("text") or "")[:_MAX_ATOM_CHARS],
                    "authority_class": atom.get("authority_class"),
                    "confidence": round(float(atom.get("confidence", 0.0)), 4),
                    "atom_type": atom.get("atom_type"),
                }
            )
            total += 1
        bundles[pack_id] = kept

    # Contradictions (pre-derived by evidence_runtime).
    contradictions = [
        {
            "edge_id": c.edge.get("id", ""),
            "from_atom_id": c.edge.get("from_atom_id", ""),
            "to_atom_id": c.edge.get("to_atom_id", ""),
            "reason": c.edge.get("reason", ""),
            "from_text": (c.from_atom.get("text") or "")[:160] if c.from_atom else "",
            "to_text": (c.to_atom.get("text") or "")[:160] if c.to_atom else "",
        }
        for c in inputs.contradictions
    ]

    return {
        "pack_prior_top": pack_summary_top,
        "pack_prior_scores": pack_summary,
        "active_packs": active_packs,
        "site_clusters": sites,
        "contradictions": contradictions,
        "retrieval_bundles": bundles,
    }


_SYSTEM = """
You are the OrbitBrief planner. You synthesize a single JSON BriefState
that downstream brains and reviewers consume. You DO NOT write prose.

Hard rules:
1. Output a single JSON object that conforms exactly to the schema
   described in the user message. No Markdown, no commentary, no
   leading/trailing whitespace.
2. Every claim in `claims` MUST cite `supporting_atom_ids` drawn from
   the `retrieval_bundles` provided in the user message. Inventing atom
   ids is a hard error.
3. Every claim's `pack_id` (when set) must be one of the active packs.
4. Pack activation status: `active` for packs the engagement clearly
   needs; `inactive` for packs explicitly out-of-scope; `watch` for
   weak signals worth surfacing but not running brains for.
5. Site `role` is `primary` for the engagement's main delivery sites,
   `secondary` for supporting sites (HQ for a regional rollout),
   `out_of_scope` for sites mentioned but not part of the work.
6. Contradiction `severity`: `info` for minor disagreements,
   `warning` for material disagreements that need reviewer attention,
   `blocker` for ones that prevent compiling a defensible brief.
7. Length caps (the JSON validator will reject violations):
   - claim.statement ≤ 500 chars
   - rationale ≤ 400 chars
   - review_flag.message ≤ 400 chars
8. `orchestration` directives are imperative instructions for the
   downstream orchestrator. Use:
   - `run_brain`: target = brain id (e.g. `bom_brain`)
   - `request_review`: target = reviewer role (e.g. `domain_expert`)
   - `skip_pack`: target = pack id
   - `request_clarification`: target = pack id or `customer`

Use temperature=0 reasoning. Be conservative on confidence: assign
0.95 only when evidence is unambiguous; 0.5 for one-source claims.
"""

_USER_TEMPLATE = """
Project: {project_id}
Compile: {compile_id}
Generated at: {generated_at}

Below is the deterministic substrate (pack prior, site clusters,
retrieval bundles, contradictions). Synthesize a BriefState JSON
object using ONLY this evidence.

Required top-level keys:
  project_id, compile_id, generated_at, pack_activations, sites,
  claims, contradictions, review_flags, orchestration, model_used,
  tier, escalation_log, token_cost

Substrate snapshot:
{snapshot_json}

Reply with the JSON object only.
"""
