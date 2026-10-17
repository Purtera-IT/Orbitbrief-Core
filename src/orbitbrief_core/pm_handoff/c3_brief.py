"""The PM handoff read from the super heads' brief (parser-os ``c3_brief``).

parser-os now decides what goes in the brief with trained heads (base layer =
any field-services company, Purtera layer = company policy) and writes it
with one cited call; the result rides on the envelope as ``c3_brief``. Until
this module the handoff page ignored it and ran its own question pipeline.

Behind ``ORBITBRIEF_C3_BRIEF`` (off unless set; dev sets it). When on and the
envelope carries a written brief:

* ``customer_questions`` = the deal's own open questions (asked in the
  documents, cited) then the catalog questions the base head asked, most
  likely first. Questions the deal already answers are not asked.
* ``one_line_summary`` = the brief's cited summary, citations stripped.
* The old pipeline's questions are kept in ``customer_questions_pool``, so
  nothing it found is lost while the two are compared.

Severity is not a head yet, so every head question is a ``warning``; no
question is promoted to ``blocker`` without one.
"""
from __future__ import annotations

import os
import re
from typing import Any

from orbitbrief_core.pm_handoff.models import GapCard

_CITE = re.compile(r"\s*\[(?:[a-z]+_[0-9a-zA-Z_]+(?:,\s*)?)+\]")
_FAMILY_LABEL = {
    "compliance_safety": "Compliance / safety",
    "commercial_terms": "Commercial terms",
}


def enabled() -> bool:
    return os.environ.get("ORBITBRIEF_C3_BRIEF", "").strip().lower() in ("1", "on", "true", "yes")


def written(envelope: Any) -> dict[str, Any] | None:
    """The written c3 brief, or None when the envelope has none."""
    if not isinstance(envelope, dict):
        return None
    brief = envelope.get("c3_brief")
    w = brief.get("written") if isinstance(brief, dict) else None
    return w if isinstance(w, dict) and (w.get("summary") or w.get("catalog_questions")) else None


def _label(family: str) -> str:
    return _FAMILY_LABEL.get(family) or family.replace("_", " ").strip().capitalize() or "Open question"


def _sources(cites: list[Any], atoms: dict[str, dict], files: dict[str, str]) -> list[dict[str, Any]]:
    out = []
    for c in cites or []:
        aid = str(c).strip("[] ")
        a = atoms.get(aid)
        if not a:
            continue
        loc = a.get("locator") if isinstance(a.get("locator"), dict) else {}
        art = str(a.get("artifact_id") or "")
        text = str(a.get("text") or "")
        out.append({"filename": files.get(art) or art, "artifact_id": art, "atom_id": aid,
                    "locator": str(loc.get("kind") or ""),
                    "snippet": text[:200] + ("…" if len(text) > 200 else ""), "media": "text"})
    return out


def strip_cites(text: str) -> str:
    return _CITE.sub("", str(text or "")).strip()


def questions(envelope: dict[str, Any]) -> list[GapCard]:
    w = written(envelope) or {}
    atoms = {str(a.get("id")): a for a in envelope.get("atoms") or [] if isinstance(a, dict)}
    files = {str(d.get("artifact_id")): str(d.get("filename") or "")
             for d in (envelope.get("documents") or envelope.get("artifacts") or []) if isinstance(d, dict)}
    cards: list[GapCard] = []
    for i, q in enumerate(w.get("open_questions") or []):
        text = strip_cites(q.get("question") or "")
        if not text:
            continue
        cards.append(GapCard(
            rule_id=f"c3:deal:{i}", domain_id="deal", domain_label="Asked in this deal",
            label=text[:80], severity="warning", message="Asked in the deal's documents, not yet answered",
            suggested_open_question=text, observed_summary=f"owner: {q.get('owner') or 'project_manager'}",
            sources=_sources(q.get("cites") or [], atoms, files)))
    catalog = sorted(w.get("catalog_questions") or [], key=lambda q: -float(q.get("p") or 0))
    for q in catalog:
        text = strip_cites(q.get("question") or "")
        if not text:
            continue
        fam = str(q.get("family") or "")
        cards.append(GapCard(
            rule_id=f"c3:{q.get('id')}", domain_id=fam or "catalog", domain_label=_label(fam),
            label=text[:80], severity="warning",
            message=f"Not answered in the deal (base head, p={float(q.get('p') or 0):.2f})",
            suggested_open_question=text, observed_summary=f"owner: {q.get('owner') or 'project_manager'}",
            sources=_sources(q.get("cites") or [], atoms, files)))
    return cards


def view(envelope: dict[str, Any]) -> dict[str, Any]:
    """What the page needs beyond questions: sections, answered questions and
    who decided, so the PM can see the heads' brief itself."""
    brief = envelope.get("c3_brief") or {}
    w = written(envelope) or {}
    return {
        "version": brief.get("version"),
        "service": brief.get("service"),
        "summary": strip_cites(w.get("summary") or ""),
        "sections": {k: [{"text": strip_cites(it.get("text") or ""), "cites": it.get("cites") or []}
                         for it in v if isinstance(it, dict)]
                     for k, v in (w.get("sections") or {}).items() if isinstance(v, list)},
        "answered_in_deal": w.get("answered_in_deal") or [],
        "decided_by": brief.get("decided_by") or {},
        "left_out": (brief.get("left_out") or {}).get("count"),
    }


_SECTION_TITLES = {"scope": "Scope", "job_details": "Job details",
                   "customer_responsibilities": "Customer responsibilities",
                   "customer_furnished": "Customer-furnished equipment",
                   "out_of_scope": "Out of scope", "schedule": "Schedule", "assumptions": "Assumptions",
                   "fees": "Fees", "terms": "Terms"}


def overview_text(v: dict[str, Any]) -> str:
    """The PM overview panel from the heads' brief: the summary, then each
    section's sentences under its name (markdown, as the panel renders it)."""
    parts = [v.get("summary") or ""]
    for key, items in (v.get("sections") or {}).items():
        text = " ".join(it["text"] for it in items if it.get("text"))
        if text:
            parts.append(f"**{_SECTION_TITLES.get(key, key.replace('_', ' ').capitalize())}.** {text}")
    return "\n\n".join(p for p in parts if p)


def headline(v: dict[str, Any]) -> str:
    """The panel's title line: the brief summary's first sentence."""
    first = re.split(r"(?<=[.!?])\s+", (v.get("summary") or "").strip(), maxsplit=1)[0]
    return first[:200]
