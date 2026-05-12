"""Output schema for :class:`SiteRealityEngine`."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SiteCluster(BaseModel):
    """One site identity, recovered from the entity + edge graph."""

    model_config = ConfigDict(frozen=True)

    cluster_id: str  # stable, derived from min site key
    canonical_name: str
    candidate_names: tuple[str, ...]  # all aliases in deterministic order
    site_keys: tuple[str, ...]  # all ``site:*`` entity_keys merged here
    member_atom_ids: tuple[str, ...]
    artifact_ids: tuple[str, ...]
    name_resolved_by_llm: bool = False
    confidence: float = Field(ge=0.0, le=1.0)


class SiteRealityState(BaseModel):
    """Deterministic JSON state emitted by :meth:`SiteRealityEngine.compute`."""

    model_config = ConfigDict(frozen=True)

    project_id: str
    compile_id: str
    clusters: tuple[SiteCluster, ...]
    cluster_count: int = Field(ge=0)
    escalation_log: dict[str, Any] = Field(default_factory=dict)
    # Number of unique site:* entity keys that were merged into one
    # cluster — sanity metric for cross-artifact site normalization.
    merged_keys: int = Field(default=0, ge=0)
