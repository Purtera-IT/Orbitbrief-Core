"""Assemble typed :class:`RetrievalBundle` instances from an :class:`EvidenceRuntime`.

Brains can't read the runtime directly (Phase-5 isolation rules),
so the orchestrator runs this assembler *for them*. Per active
pack, we filter packets to the ones whose atom text actually
matches the pack's keywords + boosted_keywords, attach compact
text snippets, and emit one :class:`RetrievalBundle` per pack.

The keyword filter is the speed + quality lever:

* Without it, every brain gets every packet (capped at 40/family).
  On a cabling-heavy engagement, the ``msp`` brain would receive
  ~95 packets, most of them cabling-themed → blown prompt budget,
  fallback skeleton.
* With it, ``msp`` only sees packets whose atoms mention MSP
  vocabulary (NOC, SOC, monitoring, RMM, ticketing, …). On the
  same engagement the cabling brain still sees 90+ packets
  (cabling vocab matches almost every atom in a cabling case);
  msp sees ~10 — small enough to fit the prompt, dense enough to
  produce real items.

If a pack has no keyword config (or no packets match), we fall
back to the unfiltered list so the brain isn't starved.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from orbitbrief_core.brains._retrieval_bundle import (
    PacketSnippet,
    RetrievalBundle,
)
from orbitbrief_core.evidence_runtime.runtime import EvidenceRuntime, RuntimeKey


# Per-pack hard cap. Stays generous for the dominant pack; the
# keyword filter trims the long tail before this cap matters.
_PACKETS_PER_FAMILY_CAP = 40
# Atom-text snippet trim.
_MAX_SNIPPET_CHARS = 280
# Minimum keyword hits per packet for it to survive the per-pack
# filter. 1 = any-match (loose, prefers recall), 2 = double-match
# (tighter, prefers precision). Default 1 + a fallback to top-N
# when nothing scores keeps weak packs from starving.
_MIN_KEYWORD_HITS = 1
# When the keyword filter produces too few packets for a brain to
# be useful, top up to this floor with the highest-density packets
# (or the lowest-id packets if no scoring data exists).
_MIN_PACKETS_PER_PACK_AFTER_FILTER = 6
_TOKEN = re.compile(r"[a-z0-9_]+")

# Atom review_flags that mark an atom as "QA marker only — do NOT
# surface in PM-facing brief content". These atoms are still kept in
# the runtime so the inspection report and review UI can show them
# (the reviewer wants to know that a low-text PDF page was found, or
# that an unchecked checkbox is ambiguous), but bundle assembly
# strips them before brains see them so they can't be cited as
# scope evidence in the final brief.
_DO_NOT_PUBLISH_FLAGS: frozenset[str] = frozenset(
    {
        "visual_evidence_not_fully_extracted",
        "do_not_certify_as_exclusion",
        "unchecked_checkbox_ambiguous",
    }
)


def _atom_is_publishable(atom: dict[str, Any] | None) -> bool:
    if atom is None:
        return False
    flags = atom.get("review_flags") or ()
    if not flags:
        return True
    return not any(f in _DO_NOT_PUBLISH_FLAGS for f in flags)


@dataclass
class BundleAssembler:
    """Stateless wrapper around an :class:`EvidenceRuntime`."""

    runtime: EvidenceRuntime
    key: RuntimeKey | None = None
    # Optional: ``pack_id → set[str]`` of keyword tokens used to filter
    # the per-pack bundle. The pipeline supplies these from the world
    # model's domain registry (keywords + boosted_keywords). Pack ids
    # not in the dict get the unfiltered top-N (back-compat).
    pack_keywords: dict[str, set[str]] = field(default_factory=dict)

    def assemble(self, *, pack_id: str) -> RetrievalBundle:
        """One :class:`RetrievalBundle` for ``pack_id`` — keyword-filtered."""
        rk = self.key or self.runtime.default_key
        if rk is None:
            raise ValueError("BundleAssembler.assemble: runtime has no default key")

        envelope = self.runtime.to_envelope_dict(rk)
        atom_index: dict[str, dict[str, Any]] = {
            a["id"]: a for a in (envelope.get("atoms") or ())
        }
        packets = list(envelope.get("packets") or [])
        if not packets:
            return RetrievalBundle(
                project_id=rk.project_id,
                compile_id=rk.compile_id,
                packets_by_family={},
            )

        # Score every packet by keyword density against this pack's vocab.
        keywords = self.pack_keywords.get(pack_id) or set()
        scored: list[tuple[int, dict[str, Any]]] = []
        for raw in packets:
            score = (
                self._packet_keyword_score(raw, atom_index, keywords)
                if keywords
                else 1  # no vocab → keep everything; cap below handles bloat
            )
            scored.append((score, raw))

        # Filter to keyword-positive packets, OR fall back to top-N by
        # id (deterministic) if nothing matched.
        keep: list[dict[str, Any]] = [r for s, r in scored if s >= _MIN_KEYWORD_HITS]
        if len(keep) < _MIN_PACKETS_PER_PACK_AFTER_FILTER:
            # Top up from the highest-scored zero-keyword packets so a
            # weak pack with poor vocab match still gets a viable bundle.
            extras = sorted(
                (r for s, r in scored if s < _MIN_KEYWORD_HITS),
                key=lambda r: str(r.get("id") or ""),
            )
            need = _MIN_PACKETS_PER_PACK_AFTER_FILTER - len(keep)
            keep.extend(extras[:need])

        # Group by family + apply per-family cap.
        by_family: dict[str, list[PacketSnippet]] = defaultdict(list)
        # Sort by (family, packet_id) for deterministic output.
        keep.sort(key=lambda r: (str(r.get("family") or ""), str(r.get("id") or "")))
        for raw in keep:
            family = raw.get("family") or ""
            if not family:
                continue
            if len(by_family[family]) >= _PACKETS_PER_FAMILY_CAP:
                continue
            by_family[family].append(self._packet_to_snippet(raw, atom_index))

        packets_by_family = {f: tuple(snips) for f, snips in by_family.items()}
        return RetrievalBundle(
            project_id=rk.project_id,
            compile_id=rk.compile_id,
            packets_by_family=packets_by_family,
        )

    # ───── internals ─────

    @staticmethod
    def _packet_keyword_score(
        raw: dict[str, Any],
        atom_index: dict[str, dict[str, Any]],
        keywords: set[str],
    ) -> int:
        """Count how many keyword tokens appear in the packet's atom text + anchor."""
        if not keywords:
            return 0
        haystack_parts: list[str] = [str(raw.get("anchor_key") or "")]
        cited_ids = set(raw.get("governing_atom_ids") or ()) | set(
            raw.get("supporting_atom_ids") or ()
        )
        for aid in cited_ids:
            atom = atom_index.get(aid)
            if atom is None:
                continue
            text = atom.get("text") or ""
            if text:
                haystack_parts.append(text)
        haystack = " ".join(haystack_parts).lower()
        if not haystack:
            return 0
        # Tokenize once; count how many distinct keyword tokens are
        # present (de-duped per packet so a chatty atom doesn't inflate
        # the score).
        tokens = set(_TOKEN.findall(haystack))
        return sum(1 for kw in keywords if kw in tokens)

    @staticmethod
    def _packet_to_snippet(
        raw: dict[str, Any], atom_index: dict[str, dict[str, Any]]
    ) -> PacketSnippet:
        # Filter atoms flagged as QA-only / do-not-publish out of
        # every cited list AND the snippet text. Brains never see
        # them, so they can't be cited as scope evidence in the
        # final brief. The atoms still exist in the runtime for
        # inspection / review UI use.
        def _publishable(ids: tuple[str, ...]) -> tuple[str, ...]:
            return tuple(a for a in ids if _atom_is_publishable(atom_index.get(a)))

        gov = _publishable(tuple(raw.get("governing_atom_ids") or ()))
        sup = _publishable(tuple(raw.get("supporting_atom_ids") or ()))
        contra = _publishable(tuple(raw.get("contradicting_atom_ids") or ()))
        cited_ids = set(gov) | set(sup) | set(contra)
        atom_text: dict[str, str] = {}
        for aid in cited_ids:
            atom = atom_index.get(aid)
            if atom is None:
                continue
            text = atom.get("text") or ""
            if text:
                atom_text[aid] = text[:_MAX_SNIPPET_CHARS]
        return PacketSnippet(
            packet_id=str(raw.get("id") or ""),
            family=str(raw.get("family") or ""),
            anchor_type=str(raw.get("anchor_type") or ""),
            anchor_key=str(raw.get("anchor_key") or ""),
            status=str(raw.get("status") or ""),
            confidence=float(raw.get("confidence") or 0.0),
            governing_atom_ids=gov,
            supporting_atom_ids=sup,
            contradicting_atom_ids=contra,
            atom_text=atom_text,
        )
