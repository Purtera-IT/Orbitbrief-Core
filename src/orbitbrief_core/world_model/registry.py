"""Domain pack registry — loaded from ``world_model/data/domain_packs.yaml``.

The YAML is the canonical source extracted from the AWESOME_CHASE
intake workbook (see ``tools/extract_domain_packs.py``). This
module wraps it in typed accessors so the pack-prior and site-
reality engines aren't reading raw YAML bags.
"""
from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from typing import Iterable

import yaml


@dataclass(frozen=True)
class DomainPack:
    """One OrbitBrief domain pack as defined in the intake workbook.

    ``keywords`` come from the workbook's notes (auto-extracted —
    cheap to refresh, sometimes generic). ``boosted_keywords`` are
    hand-curated discriminators for that pack (product names, key
    abbreviations, technology terms). The router scores boosted
    matches at higher weight.
    """

    id: str
    display_name: str
    intake_aliases: tuple[str, ...]
    subdomain_labels: tuple[str, ...]
    keywords: tuple[str, ...]
    boosted_keywords: tuple[str, ...] = ()
    # Boss-review v9 C001-F1 / C002-F1 — optional per-pack anchor
    # gating used by the router AFTER raw scoring. A pack is only
    # admitted to ``selected_pack_ids`` when the corpus contains at
    # least ``required_anchor_min_distinct_hits`` distinct matches
    # of ``required_anchor_regex_any``. Empty tuple = no gate.
    required_anchor_regex_any: tuple[str, ...] = ()
    required_anchor_min_distinct_hits: int = 2


class DomainPackRegistry:
    """In-memory index of all packs, keyed by id."""

    def __init__(self, packs: Iterable[DomainPack]) -> None:
        ordered = sorted(packs, key=lambda p: p.id)
        self._by_id: dict[str, DomainPack] = {p.id: p for p in ordered}
        # Inverted indexes: keyword → packs. Separate maps for the
        # two weight classes so the router can score boost hits at
        # higher value without having to check every keyword's class.
        self._keyword_to_pack_ids: dict[str, list[str]] = {}
        self._boost_keyword_to_pack_ids: dict[str, list[str]] = {}
        for pack in ordered:
            for kw in pack.keywords:
                self._keyword_to_pack_ids.setdefault(kw, []).append(pack.id)
            for kw in pack.boosted_keywords:
                self._boost_keyword_to_pack_ids.setdefault(kw, []).append(pack.id)

    @classmethod
    def load(cls) -> "DomainPackRegistry":
        """Load the bundled registry from packaged data."""
        # Resolve via parent package so we don't require ``data`` to
        # be its own importable subpackage. Works for source checkouts
        # and installed wheels alike.
        text = (
            resources.files("orbitbrief_core.world_model")
            .joinpath("data/domain_packs.yaml")
            .read_text(encoding="utf-8")
        )
        return cls._from_yaml_text(text)

    @classmethod
    def _from_yaml_text(cls, text: str) -> "DomainPackRegistry":
        doc = yaml.safe_load(text) or {}
        packs: list[DomainPack] = []
        for raw in doc.get("packs", []) or []:
            packs.append(
                DomainPack(
                    id=str(raw["id"]),
                    display_name=str(raw.get("display_name") or raw["id"]),
                    intake_aliases=tuple(raw.get("intake_aliases") or ()),
                    subdomain_labels=tuple(raw.get("subdomain_labels") or ()),
                    keywords=tuple(raw.get("keywords") or ()),
                    boosted_keywords=tuple(raw.get("boosted_keywords") or ()),
                    required_anchor_regex_any=tuple(
                        raw.get("required_anchor_regex_any") or ()
                    ),
                    required_anchor_min_distinct_hits=int(
                        raw.get("required_anchor_min_distinct_hits") or 2
                    ),
                )
            )
        return cls(packs)

    # ───── access ─────

    def __len__(self) -> int:
        return len(self._by_id)

    def __iter__(self):
        return iter(self._by_id.values())

    def get(self, pack_id: str) -> DomainPack | None:
        return self._by_id.get(pack_id)

    def all_ids(self) -> list[str]:
        return list(self._by_id.keys())

    def packs_for_keyword(self, keyword: str) -> list[str]:
        """Pack ids that consider ``keyword`` a routing signal (case-sensitive, lowercased)."""
        return list(self._keyword_to_pack_ids.get(keyword, ()))

    def packs_for_boost_keyword(self, keyword: str) -> list[str]:
        """Pack ids whose hand-curated boost list contains ``keyword``."""
        return list(self._boost_keyword_to_pack_ids.get(keyword, ()))


def load_default_registry() -> DomainPackRegistry:
    """Convenience alias for the bundled registry."""
    return DomainPackRegistry.load()
