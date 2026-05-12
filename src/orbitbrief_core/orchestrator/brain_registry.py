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

from orbitbrief_core.brains.managed_services import ManagedServicesBrain
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
    """The OrbitBrief default registry. Today: ``msp`` only."""
    reg = BrainRegistry()
    reg.register("msp", lambda chat: ManagedServicesBrain(chat_client=chat))
    return reg
