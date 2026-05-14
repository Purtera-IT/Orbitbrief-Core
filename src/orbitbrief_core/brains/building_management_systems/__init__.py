"""BuildingManagementSystems brain (PR 19).

Briefing-shaped output (canonical 9 sections), thin wrapper around
:class:`BriefingBrain`. Domain config sourced from
`brains/data/briefing_configs.yaml` (loaded by domain_id).
"""
from __future__ import annotations

from orbitbrief_core.brains._briefing import (
    BriefingItem,
    BriefingState,
    CANONICAL_SECTIONS,
)
from orbitbrief_core.brains._briefing_config import load_briefing_config
from orbitbrief_core.brains._briefing_runner import (
    BriefingBrain,
    BriefingBrainResult,
)
from orbitbrief_core.inference.client import ChatClient


DOMAIN_ID = "building_management_systems"


class BuildingManagementSystemsBrain(BriefingBrain):
    """Thin :class:`BriefingBrain` subclass for the building_management_systems pack."""

    def __init__(
        self,
        chat_client: ChatClient,
        *,
        model: str = "qwen3:14b",
        max_output_tokens: int | None = None,
        max_retries: int = 1,
    ) -> None:
        cfg = load_briefing_config(DOMAIN_ID)
        super().__init__(
            domain_id=DOMAIN_ID,
            config=cfg,
            chat_client=chat_client,
            model=model,
            max_output_tokens=max_output_tokens or 6144,
            max_retries=max_retries,
        )


BuildingManagementSystemsScopeState = BriefingState

__all__ = [
    "BriefingItem",
    "BriefingState",
    "CANONICAL_SECTIONS",
    "DOMAIN_ID",
    "BuildingManagementSystemsBrain",
    "BuildingManagementSystemsScopeState",
    "BriefingBrainResult",
]
