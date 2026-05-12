"""Pack-id → brain factory registry.

Adding a new brain is two lines: write the brain (Phase 5
template), then ``registry.register("<pack_id>", lambda chat: MyBrain(chat))``.

The factory takes a :class:`ChatClient` and returns a brain
instance whose ``compose(brief, bundle)`` returns a typed state
the calibrator + validator know how to walk.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from orbitbrief_core.brains.datacenter import DatacenterBrain
from orbitbrief_core.brains.imac import ImacBrain
from orbitbrief_core.brains.low_voltage_cabling import LowVoltageCablingBrain
from orbitbrief_core.brains.managed_services import ManagedServicesBrain
from orbitbrief_core.brains.rack_and_stack import RackAndStackBrain
from orbitbrief_core.brains.wireless import WirelessBrain
from orbitbrief_core.inference.client import ChatClient


# A factory takes a chat client and produces a brain instance.
BrainFactory = Callable[[ChatClient], object]


@dataclass
class BrainRegistry:
    """Maps an OrbitBrief pack id to a :type:`BrainFactory`."""

    _factories: dict[str, BrainFactory] = field(default_factory=dict)

    def register(self, pack_id: str, factory: BrainFactory) -> None:
        if not pack_id:
            raise ValueError("pack_id must be non-empty")
        self._factories[pack_id] = factory

    def get(self, pack_id: str) -> BrainFactory | None:
        return self._factories.get(pack_id)

    def known_pack_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))

    def __len__(self) -> int:
        return len(self._factories)


def default_brain_registry() -> BrainRegistry:
    """The OrbitBrief default registry — Phase 7.5 wires six brains.

    * ``msp``                  → :class:`ManagedServicesBrain` (7-section)
    * ``wireless``             → :class:`WirelessBrain` (briefing 9-section)
    * ``low_voltage_cabling``  → :class:`LowVoltageCablingBrain`
    * ``rack_and_stack``       → :class:`RackAndStackBrain`
    * ``datacenter``           → :class:`DatacenterBrain`
    * ``imac``                 → :class:`ImacBrain`
    """
    reg = BrainRegistry()
    reg.register("msp", lambda chat: ManagedServicesBrain(chat_client=chat))
    reg.register("wireless", lambda chat: WirelessBrain(chat_client=chat))
    reg.register(
        "low_voltage_cabling",
        lambda chat: LowVoltageCablingBrain(chat_client=chat),
    )
    reg.register(
        "rack_and_stack",
        lambda chat: RackAndStackBrain(chat_client=chat),
    )
    reg.register("datacenter", lambda chat: DatacenterBrain(chat_client=chat))
    reg.register("imac", lambda chat: ImacBrain(chat_client=chat))
    return reg


# Pack ids whose brains emit the canonical 9-section :class:`BriefingState`.
# Used by the orchestrator pipeline to dispatch validator / calibrator
# methods correctly without instance-checking.
BRIEFING_PACK_IDS: frozenset[str] = frozenset({
    "wireless",
    "low_voltage_cabling",
    "rack_and_stack",
    "datacenter",
    "imac",
})
