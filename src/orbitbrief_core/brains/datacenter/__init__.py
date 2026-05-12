"""Datacenter brain (Phase 7.5).

Briefing-shaped output (canonical 9 sections) with prompt sourced from
the OrbitBrief intake workbook (D07_datacenter). The workbook's per-field
guidance is layered with sensible domain defaults — refresh by running
``python tools/extract_briefing_configs.py <workbook.xlsx>`` whenever
the workbook fills in.
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


DOMAIN_ID = "datacenter"


class DatacenterBrain(BriefingBrain):
    """Datacenter OrbitBrief brain. Thin :class:`BriefingBrain` subclass."""

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


# Public alias for type hints.
DatacenterScopeState = BriefingState

__all__ = [
    "BriefingItem",
    "BriefingState",
    "CANONICAL_SECTIONS",
    "DOMAIN_ID",
    "DatacenterBrain",
    "DatacenterScopeState",
    "BriefingBrainResult",
]
