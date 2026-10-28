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

import hashlib
import logging
import os
import re
from typing import Any

log = logging.getLogger(__name__)

from orbitbrief_core.pm_handoff.models import GapCard

_CITE = re.compile(r"\s*\[(?:[a-z]+_[0-9a-zA-Z_]+(?:,\s*)?)+\]")
_FAMILY_LABEL = {
    "compliance_safety": "Compliance / safety",
    "commercial_terms": "Commercial terms",
}


def enabled() -> bool:
    return os.environ.get("ORBITBRIEF_C3_BRIEF", "").strip().lower() in ("1", "on", "true", "yes")


def heads(envelope: Any) -> dict[str, Any] | None:
    """The heads' structured brief (``c3_brief`` with ``sections``), written or
    not, or None when parser-os sent none."""
    brief = envelope.get("c3_brief") if isinstance(envelope, dict) else None
    return brief if isinstance(brief, dict) and isinstance(brief.get("sections"), dict) else None


def state(envelope: Any) -> str:
    """``ok`` (heads decided and the writer wrote), ``unwritten`` (heads decided,
    the writing call failed) or ``missing`` (no heads' brief on the envelope)."""
    if written(envelope):
        return "ok"
    return "unwritten" if heads(envelope) else "missing"


BANNER = {
    "unwritten": "The heads decided this brief but its writing step failed: lines are shown as the "
                 "documents word them.",
    "missing": "Heads unavailable: parser-os sent no heads' brief for this compile, so this page was "
               "built by Core's older rules.",
}


def kept_lines(envelope: Any) -> dict[str, str]:
    """Every line the heads kept (brief body or "also mentioned") -> the
    heads' type for it. Lines the heads left out, rejected or found
    superseded are absent."""
    brief = heads(envelope) or {}
    out: dict[str, str] = {}
    for items in (brief.get("sections") or {}).values():
        for it in items if isinstance(items, list) else []:
            if isinstance(it, dict) and it.get("id"):
                out.setdefault(str(it["id"]), str(it.get("type") or ""))
    for it in brief.get("also_mentioned") or []:
        if isinstance(it, dict) and it.get("id"):
            out.setdefault(str(it["id"]), "")
    return out


def heads_report(report: dict[str, Any], kept: dict[str, str]) -> dict[str, Any]:
    """The inspection report cut to the lines the heads kept, each carrying the
    heads' type: per-artifact atoms, the atom lineage, top-level atoms and the
    embedded envelope's atoms. The one place every report-reading panel
    (facts, risks, RFP lines, acceptance, compliance, ...) is made to follow
    the heads."""

    def cut(rows: Any) -> list[dict[str, Any]]:
        out = []
        for a in rows or []:
            aid = str(a.get("id") or a.get("atom_id") or "") if isinstance(a, dict) else ""
            if aid in kept:
                out.append({**a, "atom_type": kept[aid] or a.get("atom_type")})
        return out

    out = {**report, "artifacts": [{**art, "atoms": cut(art.get("atoms"))}
                                   for art in report.get("artifacts") or [] if isinstance(art, dict)]}
    for key in ("atom_lineage", "atoms"):
        if isinstance(report.get(key), list):
            out[key] = cut(report[key])
    if isinstance(report.get("envelope"), dict):
        out["envelope"] = {**report["envelope"], "atoms": cut(report["envelope"].get("atoms"))}
    return out


def _section_items(envelope: Any, *names: str) -> list[dict[str, Any]]:
    secs = (heads(envelope) or {}).get("sections") or {}
    return [it for n in names for it in secs.get(n) or [] if isinstance(it, dict) and it.get("text")]


def _filename(envelope: Any, atom_id: str) -> str:
    atoms = {str(a.get("id")): a for a in envelope.get("atoms") or [] if isinstance(a, dict)}
    files = {str(d.get("artifact_id")): str(d.get("filename") or "")
             for d in (envelope.get("documents") or envelope.get("artifacts") or []) if isinstance(d, dict)}
    art = str((atoms.get(atom_id) or {}).get("artifact_id") or "")
    return files.get(art) or art


def exclusions(envelope: Any) -> list[dict[str, Any]]:
    """Exclusions = the lines the section head put out of scope. Nothing else."""
    return [{"text": str(it["text"])[:300], "source": _filename(envelope, str(it.get("id"))),
             "atom_id": str(it.get("id"))}
            for it in _section_items(envelope, "out_of_scope")]


def responsibilities(envelope: Any) -> list[dict[str, Any]]:
    """Who does what, from the heads: customer_responsibilities and
    provider_responsibilities as the section head placed them (parser-os
    already moves a line to our scope when the owner head says technician).
    The supplier head's answer rides along on each line."""
    out = []
    for sec, party in (("customer_responsibilities", "customer"), ("provider_responsibilities", "provider")):
        for it in _section_items(envelope, sec):
            row = {"party": party, "text": str(it["text"])[:300],
                   "source": _filename(envelope, str(it.get("id"))), "atom_id": str(it.get("id"))}
            if it.get("supplier"):
                row["supplier"] = it["supplier"]
            out.append(row)
    return out


#: The service head's sure bar (parser-os c3_brief.SERVICE_BAR).
SERVICE_BAR = 0.6


def service_routing(envelope: Any) -> dict[str, Any] | None:
    """The service head's answer as Core's routing, when the head is sure.
    The head's labels are Core's pack ids. None when the heads give no sure
    service (absent, ``unsure``, below the bar, or the parse's own pack)."""
    svc = (heads(envelope) or {}).get("service") or {}
    value = str(svc.get("value") or "")
    by = str(svc.get("by") or "")
    if (not value or value in ("_absent", "default_pack", "other") or svc.get("unsure")
            or not by.startswith(("base:", "purtera:")) or float(svc.get("p") or 0) < SERVICE_BAR):
        return None
    return {"primary": value, "confidence": float(svc.get("p") or 0), "source": "c3_brief", "by": by}


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


def _qid(kind: str, q: dict[str, Any], text: str, taken: set[str]) -> str:
    """A question id from its content, not its position: the line it cites
    (atom ids are content hashes) or else its wording. A PM answer keyed to it
    still lands on the same question after a rebrief."""
    cites = [str(c).strip("[] ") for c in q.get("cites") or [] if str(c).strip("[] ")]
    for key in ([cites[0]] if cites else []) + [re.sub(r"\W+", " ", text.lower()).strip()]:
        rid = f"c3:{kind}:{hashlib.sha1(key.encode('utf-8')).hexdigest()[:10]}"
        if rid not in taken:
            taken.add(rid)
            return rid
    return rid


def _unwritten_questions(envelope: dict[str, Any]) -> dict[str, Any]:
    """The heads' questions when the writing call failed, as the writer's
    shape: the deal's own asks and the catalog questions, worded as found."""
    oq, cat = [], []
    for q in (heads(envelope) or {}).get("questions") or []:
        if not isinstance(q, dict) or not q.get("text"):
            continue
        if str(q.get("id") or "").startswith("q:"):
            cat.append({"id": q["id"], "question": q["text"], "family": q.get("family"), "p": q.get("p"),
                        "owner": q.get("owner"), "cites": []})
        else:
            oq.append({"question": q["text"], "owner": q.get("owner"), "cites": [q.get("id")]})
    return {"open_questions": oq, "catalog_questions": cat}


def questions(envelope: dict[str, Any]) -> list[GapCard]:
    w = written(envelope) or _unwritten_questions(envelope)
    atoms = {str(a.get("id")): a for a in envelope.get("atoms") or [] if isinstance(a, dict)}
    files = {str(d.get("artifact_id")): str(d.get("filename") or "")
             for d in (envelope.get("documents") or envelope.get("artifacts") or []) if isinstance(d, dict)}
    cards: list[GapCard] = []
    taken: set[str] = set()
    for q in w.get("open_questions") or []:
        text = strip_cites(q.get("question") or "")
        if not text:
            continue
        pricing = q.get("kind") == "pricing"
        cards.append(GapCard(
            rule_id=_qid("pricing" if pricing else "deal", q, text, taken), domain_id="pricing" if pricing else "deal",
            domain_label="Before pricing" if pricing else "Asked in this deal",
            label=text[:80], severity="warning",
            message=("Open in the deal's facts; needed to price the job" if pricing
                     else "Asked in the deal's documents, not yet answered"),
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
    sections = w.get("sections") or {}
    if not w and heads(envelope):
        # Writer failed: the heads still decided; show their lines as found.
        sections = {k: [{"text": it.get("text") or "", "cites": [it.get("id")]} for it in v if isinstance(it, dict)]
                    for k, v in (brief.get("sections") or {}).items() if k not in ("contacts", "other")}
    st = state(envelope)
    return {
        "state": st,
        **({"banner": BANNER[st]} if st in BANNER else {}),
        "version": brief.get("version"),
        "service": brief.get("service"),
        "summary": strip_cites(w.get("summary") or ""),
        "sections": {k: [{"text": strip_cites(it.get("text") or ""), "cites": it.get("cites") or []}
                         for it in v if isinstance(it, dict)]
                     for k, v in sections.items() if isinstance(v, list)},
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


def drop_settled(cards: list[GapCard], policy: Any) -> tuple[list[GapCard], int]:
    """Drop the head questions a PM already dismissed or answered on this deal
    (by id, or as a near-duplicate of the dismissed/answered ask or answer).
    Head questions never went through ``apply_feedback``, so dismissed asks
    came back on every rebrief."""
    if policy is None:
        return cards, 0
    from orbitbrief_core.pm_handoff.semantic_dedupe import is_near_duplicate_of_any

    ids = set(getattr(policy, "suppressed_rule_ids", ()) or ()) | set(getattr(policy, "answered_rule_ids", ()) or ())
    texts = list(getattr(policy, "suppressed_texts", ()) or ()) + list(getattr(policy, "answered_texts", ()) or ())
    kept = [c for c in cards if c.rule_id not in ids
            and not (texts and is_near_duplicate_of_any(c.suggested_open_question or c.label, texts))]
    return kept, len(cards) - len(kept)
