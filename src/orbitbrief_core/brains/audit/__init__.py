"""Audit brain (Phase 7.5 expansion).

Briefing-shaped output (canonical 9 sections), thin wrapper around
:class:`BriefingBrain`. Domain config sourced from
``brains/data/briefing_configs.yaml`` (loaded by domain_id).

Scope boundary: observation, documentation, and gap reporting (site
readiness, as-built, post-install QA, pre-cutover, compliance).
Remediation work is referenced as a follow-on dependency to the
relevant infra pack rather than absorbed here.
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


DOMAIN_ID = "audit"


class AuditBrain(BriefingBrain):
    """Thin :class:`BriefingBrain` subclass for the audit pack."""

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
            max_output_tokens=max_output_tokens or 8192,
            max_retries=max_retries,
        )


AuditScopeState = BriefingState

__all__ = [
    "BriefingItem",
    "BriefingState",
    "CANONICAL_SECTIONS",
    "DOMAIN_ID",
    "AuditBrain",
    "AuditScopeState",
    "BriefingBrainResult",
]
