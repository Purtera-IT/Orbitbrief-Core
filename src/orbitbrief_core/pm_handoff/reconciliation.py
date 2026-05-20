"""A5: Cross-document numeric / date reconciliation packets.

The PM handoff is the place where the buyer (and the SA) need to
see *every* dollar amount and *every* date that appears in the
intake package, with the file it came from. A typical managed
services deal has a dozen money values and a dozen dates spread
across the SOW, vendor quote, schedule, deal-overview brief, and
contracting packet — and they don't always agree.

What this module produces:

* A list of ``MoneyMention`` records, one per money value seen
  anywhere in the envelope, with the files that mention it and a
  short text snippet for each mention. Values are grouped by the
  canonical ``money:<integer>`` entity_key parser-os emits.

* A list of ``DateMention`` records, same shape, keyed on
  ``date:<YYYY-MM-DD>``.

* A list of ``ReconciliationFlag`` records, one per money group
  whose values are *suspiciously close* (within 25% of each other
  but not equal) and appear on different docs. Two documents
  saying "$1,800,000" and "$1,847,250" gets flagged; "$995" and
  "$1,847,250" does not.

The intent is PM-actionable: the table answers "do all the docs
agree on the contract value?" without an LLM in the loop. Values
come straight from parser-os atoms; no inference, no re-parsing.

This module is pure — give it an inspection report dict, get
records back. The markdown renderer in render_markdown.py wires
the records into PM_HANDOFF.md.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MoneyMention:
    """One money value as it appears across the intake package."""

    value: int  # canonical integer value (cents dropped — parser-os emits whole-dollar atoms)
    display: str  # human-friendly: "$1,847,250"
    sources: list[dict[str, str]] = field(default_factory=list)  # [{filename, snippet}]


@dataclass(frozen=True)
class DateMention:
    """One date as it appears across the intake package."""

    iso: str  # canonical YYYY-MM-DD
    sources: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class ReconciliationFlag:
    """A money / date group that probably needs PM attention.

    Two scenarios:
    * ``kind="money_near"`` — two money values are suspiciously
      close (within 25%) and appear on different documents. Could
      be a "total $1.8M" vs "total $1,847,250" mismatch.
    * ``kind="date_role_conflict"`` — two different dates appear
      with the same surrounding role word (e.g. "go-live"). Future
      work — not emitted in v1.
    """

    kind: str
    label: str
    values: list[dict[str, Any]]  # [{display, sources:[...]}, ...]


_MAX_SNIPPET = 160


def _short(text: str) -> str:
    text = (text or "").strip().replace("\n", " ")
    if len(text) <= _MAX_SNIPPET:
        return text
    return text[: _MAX_SNIPPET - 1] + "…"


def _display_money(value: int) -> str:
    return f"${value:,}"


def _iter_atoms_with_files(report: dict[str, Any]) -> list[tuple[dict[str, Any], str]]:
    """Yield (atom_dict, filename) for every atom in the report.

    The inspection report nests atoms under each artifact. We
    flatten so the reconciliation pass sees the file each atom
    came from in a single sweep.
    """
    out: list[tuple[dict[str, Any], str]] = []
    for art in report.get("artifacts") or []:
        filename = str(art.get("filename") or art.get("artifact_id") or "unknown")
        for atom in art.get("atoms") or []:
            out.append((atom, filename))
    return out


def build_money_mentions(report: dict[str, Any]) -> list[MoneyMention]:
    """Group every money entity_key across the envelope by value.

    Returns the list sorted by value descending so the largest
    amounts (which are usually the contract / project total)
    appear first in the PM_HANDOFF table.
    """
    by_value: dict[int, list[dict[str, str]]] = defaultdict(list)
    for atom, filename in _iter_atoms_with_files(report):
        for key in atom.get("entity_keys") or ():
            if not isinstance(key, str) or not key.startswith("money:"):
                continue
            raw = key.split(":", 1)[1]
            try:
                value = int(raw)
            except (TypeError, ValueError):
                continue
            if value <= 0:
                continue
            by_value[value].append({
                "filename": filename,
                "snippet": _short(atom.get("text") or ""),
            })

    mentions: list[MoneyMention] = []
    for value in sorted(by_value, reverse=True):
        # De-dupe sources by (filename, snippet) so a row repeated
        # via two cell references doesn't clutter the table.
        seen: set[tuple[str, str]] = set()
        deduped: list[dict[str, str]] = []
        for src in by_value[value]:
            key = (src["filename"], src["snippet"])
            if key in seen:
                continue
            seen.add(key)
            deduped.append(src)
        mentions.append(MoneyMention(value=value, display=_display_money(value), sources=deduped))
    return mentions


def build_date_mentions(report: dict[str, Any]) -> list[DateMention]:
    """Group every date entity_key across the envelope by ISO date."""
    by_date: dict[str, list[dict[str, str]]] = defaultdict(list)
    for atom, filename in _iter_atoms_with_files(report):
        for key in atom.get("entity_keys") or ():
            if not isinstance(key, str) or not key.startswith("date:"):
                continue
            iso = key.split(":", 1)[1]
            if len(iso) < 8:  # smoke: skip obviously malformed dates
                continue
            by_date[iso].append({
                "filename": filename,
                "snippet": _short(atom.get("text") or ""),
            })

    mentions: list[DateMention] = []
    for iso in sorted(by_date):
        seen: set[tuple[str, str]] = set()
        deduped: list[dict[str, str]] = []
        for src in by_date[iso]:
            key = (src["filename"], src["snippet"])
            if key in seen:
                continue
            seen.add(key)
            deduped.append(src)
        mentions.append(DateMention(iso=iso, sources=deduped))
    return mentions


def build_reconciliation_flags(
    money_mentions: list[MoneyMention],
    *,
    near_window: float = 0.25,
    min_value: int = 10_000,
) -> list[ReconciliationFlag]:
    """Flag money values that are suspiciously close but not equal.

    Two money values trigger a flag when:
      * both are >= ``min_value`` (default $10,000 — skip the noise
        of line-item unit prices),
      * their relative difference is within ``near_window`` (default
        25%) but they are NOT equal,
      * AND each appears on at least one document. (Same-file
        echoes don't count — those usually mean "$1.8M (rounded)
        elsewhere on the same page".)
    """
    candidates = [m for m in money_mentions if m.value >= min_value and m.sources]
    flags: list[ReconciliationFlag] = []
    seen_pairs: set[tuple[int, int]] = set()
    for i, a in enumerate(candidates):
        for b in candidates[i + 1 :]:
            if a.value == b.value:
                continue
            pair_key = (min(a.value, b.value), max(a.value, b.value))
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)
            larger = max(a.value, b.value)
            diff = abs(a.value - b.value) / larger
            if diff > near_window:
                continue
            files_a = {s["filename"] for s in a.sources}
            files_b = {s["filename"] for s in b.sources}
            # Require evidence in at least two distinct files between
            # the pair so a single-file rounding ("$1.85M ≈ $1,847,250")
            # doesn't become a PM action item.
            if len(files_a | files_b) < 2:
                continue
            flags.append(
                ReconciliationFlag(
                    kind="money_near",
                    label=f"{a.display} vs {b.display} ({diff * 100:.0f}% delta)",
                    values=[
                        {"display": a.display, "sources": list(a.sources)},
                        {"display": b.display, "sources": list(b.sources)},
                    ],
                )
            )
    return flags
