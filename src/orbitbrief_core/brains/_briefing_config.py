"""Loader for the bundled per-domain briefing configs.

The YAML at ``brains/data/briefing_configs.yaml`` is the source
of truth — it carries operating rules, normalization vocabularies,
per-field guidance bullets, and the workbook-known artifact-type
labels for each briefing-shaped domain.

Loading is cached at module import; the YAML is small (≤30 KB)
so we read it once and hand back :class:`DomainBriefingConfig`
instances on demand.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from typing import Any, Iterable

import yaml

from orbitbrief_core.brains._briefing import CANONICAL_SECTIONS


@dataclass(frozen=True)
class DomainBriefingConfig:
    """All workbook-derived material a briefing brain needs to prompt + validate."""

    domain_id: str
    display_name: str
    operating_rules: dict[str, Any]
    normalization: dict[str, Any]
    fields: dict[str, tuple[str, ...]]  # canonical-field → guidance bullets
    artifact_labels: tuple[str, ...]
    subdomain_notes: tuple[str, ...]
    # Per-section few-shot anchors. Each entry is a tuple of dicts with
    # ``statement`` + ``evidence_pattern`` + ``pitfalls`` keys (mirroring
    # the YAML schema). The runner injects them into the user message
    # so the LLM has concrete examples of what a senior PM writes per
    # section. Empty-tuple-friendly: domains without gold_examples
    # blocks just don't get few-shot anchors.
    gold_examples: dict[str, tuple[dict[str, Any], ...]] = field(default_factory=dict)

    def guidance_for(self, field: str) -> tuple[str, ...]:
        return self.fields.get(field, ())

    def gold_for(self, field: str) -> tuple[dict[str, Any], ...]:
        return (self.gold_examples or {}).get(field, ())

    @property
    def operating_rules_lines(self) -> tuple[str, ...]:
        """Human-readable operating-rule lines for the system prompt."""
        out: list[str] = []
        for k, v in self.operating_rules.items():
            label = k.replace("_", " ").capitalize()
            if isinstance(v, bool):
                out.append(f"- {label}: {'yes' if v else 'no'}")
            else:
                out.append(f"- {label}: {v}")
        return tuple(out)

    @property
    def normalization_summary(self) -> dict[str, Any]:
        """Compact form of the normalization block for prompt inclusion."""
        return self.normalization


@lru_cache(maxsize=1)
def _bundle() -> dict[str, Any]:
    text = (
        resources.files("orbitbrief_core.brains")
        .joinpath("data/briefing_configs.yaml")
        .read_text(encoding="utf-8")
    )
    return yaml.safe_load(text) or {}


def load_briefing_config(domain_id: str) -> DomainBriefingConfig:
    """Load the YAML config for ``domain_id`` (KeyError on unknown)."""
    bundle = _bundle()
    domains = bundle.get("domains") or {}
    if domain_id not in domains:
        raise KeyError(
            f"unknown briefing domain {domain_id!r}; "
            f"known: {sorted(domains)}"
        )
    raw = domains[domain_id]
    fields_raw = raw.get("fields") or {}
    fields: dict[str, tuple[str, ...]] = {}
    for canon in CANONICAL_SECTIONS:
        bullets = fields_raw.get(canon) or ()
        fields[canon] = tuple(bullets)
    # Per-section few-shot anchors (optional in the YAML).
    gold_raw = raw.get("gold_examples") or {}
    gold: dict[str, tuple[dict[str, Any], ...]] = {}
    for canon in CANONICAL_SECTIONS:
        items = gold_raw.get(canon) or ()
        if items:
            gold[canon] = tuple(dict(item) for item in items if isinstance(item, dict))
    return DomainBriefingConfig(
        domain_id=domain_id,
        display_name=str(raw.get("display_name") or domain_id),
        operating_rules=dict(raw.get("operating_rules") or {}),
        normalization=dict(raw.get("normalization") or {}),
        fields=fields,
        artifact_labels=tuple(raw.get("artifact_labels") or ()),
        subdomain_notes=tuple(raw.get("subdomain_notes") or ()),
        gold_examples=gold,
    )


def known_briefing_domains() -> tuple[str, ...]:
    return tuple(sorted((_bundle().get("domains") or {}).keys()))
