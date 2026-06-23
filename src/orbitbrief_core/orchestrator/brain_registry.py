"""Pack-id → brain factory registry — YAML-driven, alias-aware.

v45.3 redesign (mirrors parser-os `app/domain/pack_router.py` robustness):

* **Single source of truth** is ``domain_packs.yaml``. Each pack carries a
  ``brain:`` block declaring intent + implementation + aliases. Adding a
  brain is: (a) drop the package under ``brains/<name>/`` exposing a
  class in ``_BRAIN_IMPLEMENTATIONS``, (b) flip the pack's
  ``brain.intent`` to ``implemented`` in YAML.

* **Alias normalisation** mirrors parser's ``_service_line_to_pack_id``:
  lowercase, strip, replace ``-``/space with ``_``, then exact lookup,
  then substring match against every pack's ``brain.aliases``.

* **Redirect** — one pack's ``brain.implementation`` can point at
  another pack's brain (e.g. ``security_camera → camera_vms_operations``).
  The redirect chain is followed exactly once; circular declarations
  raise on registry build.

* **RoutingDecision** is returned on every lookup so callers (pipeline,
  telemetry) can log *why* a pack ran, was aliased, was redirected, or
  was skipped. No more silent ``"no registered brain"`` mystery skips.

* **Startup self-check** — any pack declaring ``brain.intent:
  implemented`` whose resolved implementation isn't a real brain class
  raises ``BrainRegistryError`` at construction time, so the worker
  crashes loud at boot instead of silently falling back at request
  time.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

from orbitbrief_core.brains.audio_visual import AudioVisualBrain
from orbitbrief_core.brains.audit import AuditBrain
from orbitbrief_core.brains.building_management_systems import (
    BuildingManagementSystemsBrain,
)
from orbitbrief_core.brains.camera_vms_operations import CameraVmsOperationsBrain
from orbitbrief_core.brains.das import DasBrain
from orbitbrief_core.brains.datacenter import DatacenterBrain
from orbitbrief_core.brains.electrical import ElectricalBrain
from orbitbrief_core.brains.fire_safety import FireSafetyBrain
from orbitbrief_core.brains.imac import ImacBrain
from orbitbrief_core.brains.low_voltage_cabling import LowVoltageCablingBrain
from orbitbrief_core.brains.managed_services import ManagedServicesBrain
from orbitbrief_core.brains.network_maintenance import NetworkMaintenanceBrain
from orbitbrief_core.brains.paging_mass_notification import PagingMassNotificationBrain
from orbitbrief_core.brains.procurement_finance import ProcurementFinanceBrain
from orbitbrief_core.brains.professional_services import ProfessionalServicesBrain
from orbitbrief_core.brains.rack_and_stack import RackAndStackBrain
from orbitbrief_core.brains.security_access import SecurityAccessBrain
from orbitbrief_core.brains.staff_augmentation import StaffAugmentationBrain
from orbitbrief_core.brains.telecom import TelecomBrain
from orbitbrief_core.brains.wireless import WirelessBrain
from orbitbrief_core.inference.client import ChatClient

log = logging.getLogger(__name__)


# ────────────────────────────── types ─────────────────────────────────


BrainFactory = Callable[[ChatClient], object]


class BrainRegistryError(RuntimeError):
    """Raised on malformed YAML, missing brain class, or alias collision."""


# Map brain-implementation id → class. The id matches the directory name
# under src/orbitbrief_core/brains/.  When a YAML pack declares
# ``brain.implementation: wireless`` we resolve it through this table.
_BRAIN_IMPLEMENTATIONS: dict[str, Callable[..., object]] = {
    "audio_visual": AudioVisualBrain,
    "audit": AuditBrain,
    "building_management_systems": BuildingManagementSystemsBrain,
    "camera_vms_operations": CameraVmsOperationsBrain,
    "das": DasBrain,
    "datacenter": DatacenterBrain,
    "electrical": ElectricalBrain,
    "fire_safety": FireSafetyBrain,
    "imac": ImacBrain,
    "low_voltage_cabling": LowVoltageCablingBrain,
    "managed_services": ManagedServicesBrain,
    "network_maintenance": NetworkMaintenanceBrain,
    "paging_mass_notification": PagingMassNotificationBrain,
    "procurement_finance": ProcurementFinanceBrain,
    "professional_services": ProfessionalServicesBrain,
    "rack_and_stack": RackAndStackBrain,
    "security_access": SecurityAccessBrain,
    "staff_augmentation": StaffAugmentationBrain,
    "telecom": TelecomBrain,
    "wireless": WirelessBrain,
}


@dataclass(frozen=True)
class BrainResolution:
    """Why a particular pack_id did or didn't get a brain factory.

    Mirrors parser-os's ``RoutingDecision`` so the pipeline can log a
    single record per pack explaining the dispatch path.
    """

    pack_id: str            # what the caller asked for, post-normalisation
    canonical_pack_id: str  # the YAML id we matched (after alias)
    brain_id: str | None    # the implementation id (after redirect)
    factory: BrainFactory | None
    source: str             # 'direct' | 'alias' | 'redirect' | 'unknown_pack' | 'intent_none' | 'missing_impl'
    rationale: str
    aliases_tried: tuple[str, ...] = ()

    def is_runnable(self) -> bool:
        return self.factory is not None


# ────────────────────────────── normalisation ─────────────────────────


def _normalise(s: str) -> str:
    """Same shape as parser-os's `_service_line_to_pack_id` normaliser."""
    return s.strip().lower().replace("-", "_").replace(" ", "_")


# ────────────────────────────── registry ──────────────────────────────


@dataclass
class _PackBrainSpec:
    """In-memory view of one pack's ``brain:`` YAML block."""

    pack_id: str
    intent: str               # 'implemented' | 'none'
    implementation: str       # which brain class to instantiate (post-redirect)
    aliases: tuple[str, ...]  # normalised surface forms that route to this pack


@dataclass
class BrainRegistry:
    """YAML-backed, alias-aware brain dispatcher.

    Construct via :func:`default_brain_registry()` (auto-loads the bundled
    ``domain_packs.yaml``) or :meth:`from_yaml(path)`.
    """

    _specs: dict[str, _PackBrainSpec] = field(default_factory=dict)
    _alias_index: dict[str, str] = field(default_factory=dict)  # normalised alias → canonical pack_id
    _factories: dict[str, BrainFactory] = field(default_factory=dict)  # pack_id → factory after redirect resolve

    # ── construction ────────────────────────────────────────────────

    @classmethod
    def from_yaml(cls, yaml_path: Path) -> "BrainRegistry":
        if not yaml_path.is_file():
            raise BrainRegistryError(f"domain_packs.yaml not found at {yaml_path}")
        try:
            raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise BrainRegistryError(f"malformed YAML at {yaml_path}: {exc}") from exc

        # Accept either a top-level list or a {packs: [...]} dict shape — the
        # bundled file uses the dict form (with `_doc:` and `version:` siblings).
        if isinstance(raw, dict):
            entries = raw.get("packs", [])
        elif isinstance(raw, list):
            entries = raw
        else:
            raise BrainRegistryError(
                f"{yaml_path} root must be list or {{packs: [...]}} mapping, "
                f"got {type(raw).__name__}"
            )
        if not isinstance(entries, list):
            raise BrainRegistryError(
                f"{yaml_path}: 'packs' must be a list, got {type(entries).__name__}"
            )

        specs: dict[str, _PackBrainSpec] = {}
        alias_index: dict[str, str] = {}

        for entry in entries:
            if not isinstance(entry, dict):
                continue
            pack_id = entry.get("id")
            if not isinstance(pack_id, str) or not pack_id.strip():
                raise BrainRegistryError(f"YAML pack missing id: {entry!r}")
            pack_id = pack_id.strip()

            brain_block = entry.get("brain") or {}
            if not isinstance(brain_block, dict):
                raise BrainRegistryError(
                    f"pack {pack_id!r}: 'brain' must be a mapping, got {type(brain_block).__name__}"
                )

            intent = str(brain_block.get("intent", "none")).strip().lower()
            if intent not in {"implemented", "none"}:
                raise BrainRegistryError(
                    f"pack {pack_id!r}: brain.intent must be 'implemented' or 'none', got {intent!r}"
                )
            implementation = str(brain_block.get("implementation", pack_id)).strip()
            aliases_raw = brain_block.get("aliases") or []
            if not isinstance(aliases_raw, list):
                raise BrainRegistryError(
                    f"pack {pack_id!r}: brain.aliases must be a list"
                )
            # Always include the pack_id itself + any intake_aliases as
            # routable surface forms.  This is the parser-os trick — every
            # spelling humans might use gets normalised to one canonical id.
            intake_aliases = entry.get("intake_aliases") or []
            if not isinstance(intake_aliases, list):
                intake_aliases = []
            surface_forms = [pack_id, *aliases_raw, *intake_aliases]
            normalised = tuple(_normalise(str(a)) for a in surface_forms if str(a).strip())

            specs[pack_id] = _PackBrainSpec(
                pack_id=pack_id,
                intent=intent,
                implementation=implementation,
                aliases=normalised,
            )

        # Build the alias index with deterministic collision resolution
        # (mirrors how parser-os's pack_router picks among candidates):
        #   1. an alias that IS a canonical pack id always wins for that pack
        #   2. otherwise, packs with brain.intent=implemented beat intent=none
        #      (avoids the 'other' catchall stealing routes from real packs)
        #   3. on a tie, first-declared wins, but we log a warning so the
        #      YAML can be cleaned up.
        all_alias_pairs: list[tuple[str, str]] = []  # (alias, pack_id)
        for pack_id, spec in specs.items():
            for alias in spec.aliases:
                all_alias_pairs.append((alias, pack_id))

        # First pass — canonical pack_id always claims its own normalised id.
        for pack_id in specs:
            alias_index[_normalise(pack_id)] = pack_id

        # Second pass — other aliases, with implemented > none precedence.
        for alias, pack_id in all_alias_pairs:
            existing = alias_index.get(alias)
            if existing is None:
                alias_index[alias] = pack_id
                continue
            if existing == pack_id:
                continue
            # Don't override a canonical-id claim from pass 1 (where the
            # alias IS the existing pack's normalised canonical id).
            if alias == _normalise(existing):
                continue
            existing_spec = specs[existing]
            new_spec = specs[pack_id]
            # Prefer the implemented pack over a 'none' pack.
            if existing_spec.intent == "none" and new_spec.intent == "implemented":
                log.warning(
                    "brain_registry: alias %r reassigned from %r (intent=none) "
                    "to %r (intent=implemented)", alias, existing, pack_id,
                )
                alias_index[alias] = pack_id
                continue
            if existing_spec.intent == "implemented" and new_spec.intent == "none":
                # Existing implemented pack already owns it; ignore.
                continue
            # Same intent: keep first, warn.
            log.warning(
                "brain_registry: alias %r claimed by both %r and %r "
                "(same intent=%s); keeping %r — clean domain_packs.yaml to remove ambiguity",
                alias, existing, pack_id, existing_spec.intent, existing,
            )

        reg = cls(_specs=specs, _alias_index=alias_index)
        reg._resolve_factories()
        return reg

    def _resolve_factories(self) -> None:
        """Walk every spec and bind it to a factory, with redirect resolution.

        Raises if a pack declares ``intent: implemented`` but the
        implementation id doesn't match any known brain class. That's a
        config bug we want to surface at boot, not at request time.
        """
        for pack_id, spec in self._specs.items():
            if spec.intent == "none":
                continue
            impl_id = spec.implementation
            if impl_id not in _BRAIN_IMPLEMENTATIONS:
                # Last-chance: maybe the implementation is itself another
                # pack's canonical id, follow one redirect.
                aliased = self._alias_index.get(_normalise(impl_id))
                if aliased and aliased in self._specs:
                    impl_id = self._specs[aliased].implementation
            if impl_id not in _BRAIN_IMPLEMENTATIONS:
                raise BrainRegistryError(
                    f"pack {pack_id!r}: brain.intent=implemented but "
                    f"brain.implementation={spec.implementation!r} is not a known "
                    f"brain class. Known: {sorted(_BRAIN_IMPLEMENTATIONS)}"
                )
            klass = _BRAIN_IMPLEMENTATIONS[impl_id]
            self._factories[pack_id] = lambda chat, _k=klass: _k(chat_client=chat)

    # ── lookup ──────────────────────────────────────────────────────

    def resolve(self, pack_id: str) -> BrainResolution:
        """Resolve a (possibly aliased / misspelled) pack_id to a factory + decision."""
        raw = pack_id or ""
        norm = _normalise(raw)

        # 1. Direct hit on a known canonical pack_id.
        if raw in self._specs:
            return self._decision_for(raw, source="direct",
                                       rationale=f"exact match on canonical pack_id {raw!r}")
        if norm in self._specs:
            return self._decision_for(
                norm, source="direct",
                rationale=f"exact match after normalisation: {raw!r} → {norm!r}",
            )

        # 2. Alias index — every surface form (intake_aliases + brain.aliases)
        #    is pre-normalised at build time.
        aliased = self._alias_index.get(norm)
        if aliased:
            return self._decision_for(
                aliased, source="alias",
                rationale=f"alias match: {raw!r} → {aliased!r}",
                aliases_tried=(norm,),
            )

        # 3. Substring match — try every alias as a substring of the input,
        #    same trick parser-os uses for free-text service lines.
        tried = [norm]
        for alias, canonical in self._alias_index.items():
            if alias and alias in norm:
                return self._decision_for(
                    canonical, source="alias",
                    rationale=f"substring alias match: {alias!r} in {norm!r} → {canonical!r}",
                    aliases_tried=tuple(tried + [alias]),
                )

        return BrainResolution(
            pack_id=raw,
            canonical_pack_id=raw,
            brain_id=None,
            factory=None,
            source="unknown_pack",
            rationale=(
                f"no YAML pack matches {raw!r} (normalised {norm!r}); "
                f"add an entry to domain_packs.yaml or extend brain.aliases"
            ),
            aliases_tried=tuple(tried),
        )

    def _decision_for(
        self, canonical_pack_id: str, *, source: str, rationale: str,
        aliases_tried: tuple[str, ...] = (),
    ) -> BrainResolution:
        spec = self._specs[canonical_pack_id]
        if spec.intent == "none":
            return BrainResolution(
                pack_id=canonical_pack_id,
                canonical_pack_id=canonical_pack_id,
                brain_id=None,
                factory=None,
                source="intent_none",
                rationale=(
                    f"pack {canonical_pack_id!r} matched but brain.intent=none "
                    f"(YAML declares this pack has no LLM brain by design)"
                ),
                aliases_tried=aliases_tried,
            )
        factory = self._factories.get(canonical_pack_id)
        if factory is None:
            # Shouldn't happen — _resolve_factories asserts this — but guard anyway.
            return BrainResolution(
                pack_id=canonical_pack_id,
                canonical_pack_id=canonical_pack_id,
                brain_id=spec.implementation,
                factory=None,
                source="missing_impl",
                rationale=(
                    f"pack {canonical_pack_id!r} intent=implemented but no factory bound "
                    f"(implementation={spec.implementation!r} not in _BRAIN_IMPLEMENTATIONS)"
                ),
                aliases_tried=aliases_tried,
            )
        # If the implementation differs from the pack_id, it's a redirect.
        is_redirect = spec.implementation != canonical_pack_id
        return BrainResolution(
            pack_id=canonical_pack_id,
            canonical_pack_id=canonical_pack_id,
            brain_id=spec.implementation,
            factory=factory,
            source="redirect" if is_redirect else source,
            rationale=(
                f"{rationale}; running brain {spec.implementation!r}"
                if is_redirect else f"{rationale}; brain {spec.implementation!r}"
            ),
            aliases_tried=aliases_tried,
        )

    # ── back-compat surface ─────────────────────────────────────────

    def get(self, pack_id: str) -> BrainFactory | None:
        """Back-compat shim — return factory or None. Use `resolve()` for diagnostics."""
        return self.resolve(pack_id).factory

    def register(self, pack_id: str, factory: BrainFactory) -> None:
        """Imperative override — used by tests and demo scripts.

        This bypasses the YAML self-check. Prefer extending domain_packs.yaml
        instead; this is here so existing test fixtures keep working.
        """
        if not pack_id:
            raise ValueError("pack_id must be non-empty")
        norm = _normalise(pack_id)
        spec = _PackBrainSpec(
            pack_id=pack_id, intent="implemented",
            implementation=pack_id, aliases=(norm,),
        )
        self._specs[pack_id] = spec
        self._alias_index[norm] = pack_id
        self._factories[pack_id] = factory

    def known_pack_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))

    def __len__(self) -> int:
        return len(self._factories)


# ────────────────────────────── defaults ──────────────────────────────


def _default_yaml_path() -> Path:
    """Path to the bundled domain_packs.yaml inside this package."""
    return (
        Path(__file__).resolve().parent.parent
        / "world_model" / "data" / "domain_packs.yaml"
    )


def default_brain_registry() -> BrainRegistry:
    """Build the standard registry from the bundled YAML.

    All historical pack_ids (msp, wireless, low_voltage_cabling, ...) are
    declared in YAML, so this returns the same effective surface as the
    pre-v45.3 hard-coded registry — with alias + redirect routing added.
    """
    return BrainRegistry.from_yaml(_default_yaml_path())


# ────────────────────────────── output-shape map ──────────────────────


# Pack ids whose brains emit the canonical 9-section :class:`BriefingState`.
# Used by the orchestrator pipeline to dispatch validator / calibrator
# methods correctly without instance-checking.
#
# Kept as a plain frozenset (not YAML-driven) because it's a property of
# the *brain class*, not the pack — the same brain class will always emit
# the same shape regardless of which pack id routed to it.
BRIEFING_PACK_IDS: frozenset[str] = frozenset({
    "wireless",
    "low_voltage_cabling",
    "rack_and_stack",
    "datacenter",
    "imac",
    "audio_visual",
    "building_management_systems",
    "network_maintenance",
    "camera_vms_operations",
    "procurement_finance",
    "electrical",
    "professional_services",
    "audit",
    "das",
    "fire_safety",
    "paging_mass_notification",
    "security_access",
    "staff_augmentation",
    "telecom",
    # Packs that redirect to one of the briefing brains above keep emitting
    # BriefingState — list them here so the pipeline picks the briefing
    # validator/calibrator path.
    "security_camera",  # redirects → camera_vms_operations
})
