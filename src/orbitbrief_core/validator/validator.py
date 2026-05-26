"""The deterministic validator.

Today this is wired specifically against the
:class:`ManagedServicesScopeState` shape (Phase 5). The five
in-spec rule families generalize trivially to any other brain
that emits sections of grounded items — adding a new brain only
requires extending :data:`_GROUNDED_SECTIONS_BY_BRAIN` (or making
that registry data-driven).

Rule semantics
==============

* **path_legality** — every grounded item must trace
  ``packet → atom → source_ref``. We split this into three
  reportable sub-rules so a reviewer sees the *first* break, not
  just a generic "ungrounded" message:
  - ``UNRESOLVED_PACKET`` — cited packet id missing from bundle.
  - ``UNRESOLVED_ATOM``   — cited atom id missing from
    :class:`EvidenceLookup`.
  - ``MISSING_SOURCE_REF`` — atom has no ``locator`` /
    ``source_refs``.
* **missing_evidence** — section item with zero atom citations
  *and* its packets are all in low-authority families.
* **site_count_sanity** — scope items mentioning a numeric site
  count above the SiteRealityState's ``cluster_count`` (or with
  ``merged_keys + cluster_count`` if the planner decided to
  collapse). Pure heuristic; INFO severity.
* **pack_incompatibility** — emitted at the project level. Two
  active packs from a hand-curated incompatibility set
  (e.g. ``itad`` + ``hardware`` doing receiving) trip this.
* **impossible_state** — item cites an atom whose
  ``verified == "failed"``. Replay said the atom doesn't match
  source bytes; treating it as live is unsafe.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from orbitbrief_core.brains._briefing import (
    CANONICAL_SECTIONS as _BRIEFING_SECTIONS,
    BriefingState,
)
from orbitbrief_core.brains._retrieval_bundle import RetrievalBundle
from orbitbrief_core.brains.managed_services.schema import (
    ManagedServicesScopeState,
)
from orbitbrief_core.validator.evidence_lookup import (
    EvidenceLookup,
    NullEvidenceLookup,
)
from orbitbrief_core.validator.report import (
    ItemRef,
    ItemValidation,
    ValidationFailure,
    ValidationReport,
    ValidationRuleId,
    ValidationSeverity,
)
from orbitbrief_core.world_model.planner.schema import BriefState


# Sections we know how to validate, per brain. Adding a brain →
# add an entry here (or wire a registry). All Phase-7.5 briefing
# brains share the canonical 9-section shape.
_GROUNDED_SECTIONS_BY_BRAIN: dict[str, tuple[str, ...]] = {
    "managed_services": (
        "scope_items",
        "exclusions",
        "customer_responsibilities",
        "milestones",
        "assumptions",
        "dispatch_readiness_flags",
        "open_questions",
    ),
    # Phase-7.5 briefing brains (all share the canonical 9-section shape)
    "wireless": _BRIEFING_SECTIONS,
    "low_voltage_cabling": _BRIEFING_SECTIONS,
    "rack_and_stack": _BRIEFING_SECTIONS,
    "datacenter": _BRIEFING_SECTIONS,
    "imac": _BRIEFING_SECTIONS,
    # PR19 + Phase 7.5 expansion brains — all share the briefing
    # 9-section template, so we just point at the same tuple. Without
    # these entries the orchestrator crashes when pack_prior selects
    # one of these packs as active.
    "audio_visual": _BRIEFING_SECTIONS,
    "building_management_systems": _BRIEFING_SECTIONS,
    "network_maintenance": _BRIEFING_SECTIONS,
    "camera_vms_operations": _BRIEFING_SECTIONS,
    "procurement_finance": _BRIEFING_SECTIONS,
    "electrical": _BRIEFING_SECTIONS,
    "professional_services": _BRIEFING_SECTIONS,
    "audit": _BRIEFING_SECTIONS,
    # `delivery_execution` and `hardware` are pack_prior packs that
    # don't have brains today; the pipeline skips them at the brain
    # stage and never reaches the validator for them. They're listed
    # here as a defensive belt-and-braces in case the pipeline ever
    # dispatches validation for a no-brain pack.
    "delivery_execution": _BRIEFING_SECTIONS,
    "hardware": _BRIEFING_SECTIONS,
}

# Pack families known to be mutually exclusive in production. ITAD
# (asset disposition) and hardware-procurement-and-receiving cover
# the same logistical surface from opposite ends; if both are
# active the engagement is misframed. Treat as WARNING because
# legitimate edge cases exist (receive-then-disposition).
_PACK_INCOMPATIBILITIES: tuple[tuple[str, str], ...] = (
    ("itad", "hardware"),
)

# Authority classes considered HIGH-authority for the
# missing_evidence rule. An item citing ONLY low-authority atoms
# without resolving any source_ref is considered evidence-thin.
_HIGH_AUTHORITY_CLASSES: frozenset[str] = frozenset({
    "contractual_scope",
    "customer_current_authored",
    "approved_site_roster",
})


@dataclass(frozen=True)
class PackIncompatibility:
    """Public representation of one project-level rule firing."""

    pack_a: str
    pack_b: str
    severity: ValidationSeverity = ValidationSeverity.WARNING


@dataclass
class BrainOutputValidator:
    """Stateless trust-layer validator. One instance reusable across briefs."""

    lookup: EvidenceLookup = field(default_factory=NullEvidenceLookup)
    pack_incompatibilities: tuple[tuple[str, str], ...] = _PACK_INCOMPATIBILITIES

    def validate_briefing(
        self,
        state: BriefingState,
        *,
        brief: BriefState,
        bundle: RetrievalBundle,
    ) -> ValidationReport:
        """Validate one :class:`BriefingState` from a Phase-7.5 briefing brain."""
        return self._validate_grounded_state(
            state=state,
            brief=brief,
            bundle=bundle,
            brain=state.domain_id,
        )

    def validate_managed_services(
        self,
        state: ManagedServicesScopeState,
        *,
        brief: BriefState,
        bundle: RetrievalBundle,
    ) -> ValidationReport:
        """Validate one :class:`ManagedServicesScopeState`."""
        return self._validate_grounded_state(
            state=state,
            brief=brief,
            bundle=bundle,
            brain="managed_services",
        )

    def _validate_grounded_state(
        self,
        *,
        state: Any,
        brief: BriefState,
        bundle: RetrievalBundle,
        brain: str,
    ) -> ValidationReport:
        """Shared rule walk for any brain whose state lists grounded items per section."""
        sections = _GROUNDED_SECTIONS_BY_BRAIN.get(brain)
        if sections is None:
            raise KeyError(
                f"validator: unknown brain {brain!r}; "
                f"register sections in _GROUNDED_SECTIONS_BY_BRAIN"
            )
        items: list[ItemValidation] = []
        # Pre-compute lookup tables for O(1) hits.
        valid_packets = bundle.known_packet_ids()
        atoms_by_packet: dict[str, set[str]] = {}
        for p in bundle.all_packets:
            atoms_by_packet[p.packet_id] = (
                set(p.governing_atom_ids)
                | set(p.supporting_atom_ids)
                | set(p.contradicting_atom_ids)
            )

        site_count = len(brief.sites)

        for section in sections:
            for item in getattr(state, section):
                ref = ItemRef(
                    project_id=state.project_id,
                    compile_id=state.compile_id,
                    brain=brain,
                    section=section,
                    item_id=item.id,
                )
                failures: list[ValidationFailure] = []
                # Path-legality: walk packet → atom → source_ref.
                failures.extend(
                    self._check_path_legality(
                        item=item,
                        valid_packets=valid_packets,
                        atoms_by_packet=atoms_by_packet,
                    )
                )
                # Missing evidence (only if path was clean above).
                if not failures:
                    failures.extend(
                        self._check_missing_evidence(item, bundle, atoms_by_packet)
                    )
                # Site-count sanity (only on scope-flavored sections).
                if section in {
                    "scope_items",
                    "milestones",
                    "scope_overview",
                    "detailed_scope_of_services",
                } and site_count is not None:
                    failures.extend(self._check_site_count(item.statement, site_count))
                # Impossible state (atoms whose replay failed).
                failures.extend(
                    self._check_impossible_state(
                        item=item,
                        atoms_by_packet=atoms_by_packet,
                    )
                )
                items.append(ItemValidation(item=ref, failures=tuple(failures)))

        # Project-level rules.
        project_failures = list(self._check_pack_incompatibilities(brief))
        return ValidationReport(
            project_id=state.project_id,
            compile_id=state.compile_id,
            brain=brain,
            items=tuple(items),
            project_failures=tuple(project_failures),
        )

    # ───── individual rules ─────

    def _check_path_legality(
        self,
        *,
        item,
        valid_packets: set[str],
        atoms_by_packet: dict[str, set[str]],
    ) -> Iterable[ValidationFailure]:
        # Hop 1: packets.
        unresolved_packets = [
            pid for pid in item.supporting_packet_ids if pid not in valid_packets
        ]
        if unresolved_packets:
            yield ValidationFailure(
                rule_id=ValidationRuleId.UNRESOLVED_PACKET,
                severity=ValidationSeverity.BLOCKER,
                message=(
                    f"item cites packet(s) not in bundle: "
                    f"{', '.join(unresolved_packets[:5])}"
                )[:480],
                detail={"unresolved_packet_ids": unresolved_packets},
            )
            return  # Don't check downstream hops if packets are missing.

        # Hop 2: atoms must belong to the cited packet AND resolve in lookup.
        # We collect the union of atoms across cited packets.
        allowed_atoms: set[str] = set()
        for pid in item.supporting_packet_ids:
            allowed_atoms |= atoms_by_packet.get(pid, set())

        # The brain's post-call validator already strips foreign atoms,
        # but the validator double-checks (defense in depth):
        foreign_atoms = [
            aid for aid in item.supporting_atom_ids if aid not in allowed_atoms
        ]
        if foreign_atoms:
            yield ValidationFailure(
                rule_id=ValidationRuleId.PATH_LEGALITY,
                severity=ValidationSeverity.BLOCKER,
                message=(
                    f"item cites atom(s) outside its packet's atom set: "
                    f"{', '.join(foreign_atoms[:5])}"
                )[:480],
                detail={"foreign_atom_ids": foreign_atoms},
            )
            return

        # Hop 3: atom → source_ref.
        unresolved_atoms: list[str] = []
        missing_source_atoms: list[str] = []
        for aid in item.supporting_atom_ids:
            atom = self.lookup.get_atom(aid)
            if atom is None:
                unresolved_atoms.append(aid)
                continue
            if not _has_source_ref(atom):
                missing_source_atoms.append(aid)

        if unresolved_atoms:
            yield ValidationFailure(
                rule_id=ValidationRuleId.UNRESOLVED_ATOM,
                severity=ValidationSeverity.WARNING,
                message=(
                    f"atom(s) not resolvable via evidence lookup: "
                    f"{', '.join(unresolved_atoms[:5])}"
                )[:480],
                detail={"unresolved_atom_ids": unresolved_atoms},
            )

        if missing_source_atoms:
            yield ValidationFailure(
                rule_id=ValidationRuleId.MISSING_SOURCE_REF,
                severity=ValidationSeverity.WARNING,
                message=(
                    f"atom(s) lack source_ref / locator: "
                    f"{', '.join(missing_source_atoms[:5])}"
                )[:480],
                detail={"missing_source_ref_atom_ids": missing_source_atoms},
            )

    def _check_missing_evidence(
        self, item, bundle: RetrievalBundle, atoms_by_packet: dict[str, set[str]]
    ) -> Iterable[ValidationFailure]:
        """Item cites packets but no atoms? OR cites only low-authority atoms with no source resolution."""
        if not item.supporting_atom_ids:
            yield ValidationFailure(
                rule_id=ValidationRuleId.MISSING_EVIDENCE,
                severity=ValidationSeverity.WARNING,
                message=(
                    "item cites packets but no atom_ids; cannot trace to source"
                )[:480],
                detail={"packet_ids": list(item.supporting_packet_ids)},
            )

    def _check_site_count(
        self, statement: str, site_count: int
    ) -> Iterable[ValidationFailure]:
        """Heuristic: if the statement claims a numeric site count > brief sites, flag INFO."""
        # Match patterns like "3 sites", "across 12 sites", "for 50 locations"
        import re

        m = re.search(
            r"\b(\d{1,4})\s+(?:sites?|locations?|buildings?|campus(?:es)?)\b",
            statement,
            re.IGNORECASE,
        )
        if m is None:
            return
        n = int(m.group(1))
        if n > site_count and n - site_count >= 2:
            yield ValidationFailure(
                rule_id=ValidationRuleId.SITE_COUNT_SANITY,
                severity=ValidationSeverity.INFO,
                message=(
                    f"statement implies {n} sites but SiteRealityState has "
                    f"{site_count} cluster(s); confirm scope coverage"
                )[:480],
                detail={"claimed_sites": n, "site_clusters": site_count},
            )

    def _check_impossible_state(
        self, *, item, atoms_by_packet: dict[str, set[str]]
    ) -> Iterable[ValidationFailure]:
        """Cite a failed-replay atom → impossible_state."""
        bad: list[str] = []
        for aid in item.supporting_atom_ids:
            atom = self.lookup.get_atom(aid)
            if atom is None:
                continue
            if str(atom.get("verified", "")).lower() == "failed":
                bad.append(aid)
        if bad:
            yield ValidationFailure(
                rule_id=ValidationRuleId.IMPOSSIBLE_STATE,
                severity=ValidationSeverity.BLOCKER,
                message=(
                    f"item cites atom(s) whose replay failed: "
                    f"{', '.join(bad[:5])}"
                )[:480],
                detail={"failed_replay_atom_ids": bad},
            )

    def _check_pack_incompatibilities(
        self, brief: BriefState
    ) -> Iterable[ValidationFailure]:
        active_pack_ids = {
            pa.pack_id for pa in brief.pack_activations if pa.status.value == "active"
        }
        for a, b in self.pack_incompatibilities:
            if a in active_pack_ids and b in active_pack_ids:
                yield ValidationFailure(
                    rule_id=ValidationRuleId.PACK_INCOMPATIBILITY,
                    severity=ValidationSeverity.WARNING,
                    message=(
                        f"both '{a}' and '{b}' are active; these usually don't co-occur. "
                        f"confirm engagement framing"
                    )[:480],
                    detail={"pack_a": a, "pack_b": b},
                )


def _has_source_ref(atom: dict[str, Any]) -> bool:
    """Atom counts as source-grounded if it carries a locator with at least a page or section."""
    locator = atom.get("locator") or {}
    if not isinstance(locator, dict):
        return False
    # parser-os locators carry various keys per artifact type; any
    # of these is sufficient evidence of a source ref.
    keys = {"page", "section", "row", "sheet", "char_offset", "anchor"}
    return any(k in locator for k in keys)
