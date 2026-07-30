"""Evidence-derived question generators — fill the ~50 pool with real asks.

Each generator MUST attach evidence via `_with_evidence(..., require=True)`.
No template fires without a matching atom/snippet.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

from orbitbrief_core.pm_handoff.models import SiteSummary
from orbitbrief_core.pm_handoff.question_feedback import fingerprint_question

# Import helpers from question_engine lazily inside functions where needed to
# avoid circular imports at module load (engine calls build_extended_candidates).

# Per-site decision families (rule suffix → question stem + trigger bits)
_SITE_GAP_SPECS: tuple[tuple[str, str, str, str, float], ...] = (
    (
        "circuit_ready",
        "Circuit readiness",
        "Confirm circuit / carrier readiness at {site} — ready for turn-up, or defer?",
        r"(?:circuit|carrier|underlay|wan|demarc|dia|mpls|broadband)",
        0.88,
    ),
    (
        "access_escort",
        "Site access / escort",
        "Confirm site access, escort, and badging requirements for {site}.",
        r"(?:access|escort|badg(?:e|ing)|security|loading\s+dock|after[\-\s]?hours)",
        0.86,
    ),
    (
        "onsite_contact",
        "Onsite contact",
        "Who is the day-of onsite contact for {site}, and how do we reach them?",
        r"(?:contact|site\s+lead|facilities|noc|on[\-\s]?site)",
        0.84,
    ),
    (
        "rack_power",
        "Rack / power",
        "Confirm rack space, power (amps/phase), and UPS dependency at {site}.",
        r"(?:rack|power|ups|pdu|cabinet|ru\b|amp)",
        0.83,
    ),
    (
        "cutover_window",
        "Cutover window",
        "Confirm the approved cutover / maintenance window for {site}.",
        r"(?:cutover|change\s+window|maintenance\s+window|outage|go[\-\s]?live)",
        0.85,
    ),
    (
        "acceptance",
        "Site acceptance",
        "Who signs site acceptance at {site}, and what is the pass/fail checklist?",
        r"(?:acceptance|sign[\-\s]?off|poc|sop|commission)",
        0.82,
    ),
)


def _site_name(site: SiteSummary) -> str:
    for attr in ("name", "label", "site_name", "display_name"):
        v = getattr(site, attr, None)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return "site"


def _site_id(site: SiteSummary) -> str:
    return re.sub(r"[^\w\-]+", "_", _site_name(site))[:48] or "site"


def candidates_from_sites(
    sites: list[SiteSummary],
    *,
    atoms: Iterable[Mapping[str, Any]],
    project_mode: str,
    blob: str,
    docs_by_id: Mapping[str, str] | None = None,
    max_sites: int = 12,
) -> list:
    """One evidence-grounded ask per (publishable site × open gap family)."""
    from orbitbrief_core.pm_handoff.question_engine import (
        QuestionCandidate,
        _is_customer_facing_question,
        _with_evidence,
    )

    atom_list = [a for a in atoms if isinstance(a, Mapping)]
    blob_low = (blob or "").lower()
    out = []
    pub = [s for s in sites if getattr(s, "publishable", True)][:max_sites]
    if not pub:
        pub = list(sites)[:max_sites]
    for site in pub:
        name = _site_name(site)
        sid = _site_id(site)
        name_re = re.compile(re.escape(name), re.I) if len(name) >= 3 else None
        for suffix, label, stem, trig, score in _SITE_GAP_SPECS:
            # Need site mention OR global family evidence in the blob.
            family_hit = re.search(trig, blob_low, re.I)
            site_hit = bool(name_re and name_re.search(blob or ""))
            if not family_hit and not site_hit:
                continue
            # Skip if already clearly answered for this site.
            answered = re.search(
                rf"(?i){re.escape(name)}.{{0,80}}(?:confirmed|ready|complete|signed)",
                blob or "",
            )
            if answered and suffix in {"circuit_ready", "acceptance"}:
                continue
            q = stem.format(site=name)
            if not _is_customer_facing_question(q):
                continue
            trigger = re.compile(
                rf"(?:{trig}|{re.escape(name)})",
                re.I,
            )
            cand = QuestionCandidate(
                rule_id=f"site.{sid}.{suffix}",
                domain_id="site",
                label=f"{label} — {name}",
                severity="blocker" if suffix in {"circuit_ready", "access_escort"} else "warning",
                message=f"Site-level decision still open for {name}.",
                suggested_open_question=q,
                observed_summary=f"Site gap · {name}",
                source="evidence",
                score=score,
                project_mode=project_mode,
            )
            grounded = _with_evidence(
                cand,
                atoms=atom_list,
                trigger=trigger,
                docs_by_id=docs_by_id,
                require=True,
                min_score=0.38,
            )
            if grounded is not None:
                out.append(grounded)
    return out


_PHOTO_FACT_KINDS = frozenset(
    {
        "cable",
        "mount",
        "power_data",
        "annotation",
        "display",
        "pathway",
        "rack",
        "label",
        "port",
        "device",
    }
)

_PHOTO_ASK: dict[str, str] = {
    "cable": "Confirm cable pathway / concealment method shown in this photo — in-wall, raceway, or leave as-is?",
    "mount": "Confirm mount type and location shown in this photo are approved for install.",
    "power_data": "Confirm power/data receptacle location and capacity shown in this photo.",
    "annotation": "Confirm the field annotation on this photo is in-scope for the quote.",
    "display": "Confirm keep vs remove / remount for the display shown in this photo.",
    "pathway": "Confirm the network/AV pathway method shown in this photo.",
    "rack": "Confirm rack position and RU allocation shown in this photo.",
    "label": "Confirm the labeled port/circuit identity shown in this photo matches the as-built.",
    "port": "Confirm the port assignment shown in this photo for turn-up.",
    "device": "Confirm the device model/location shown in this photo is in BOM scope.",
}


def candidates_from_photo_facts(
    atoms: Iterable[Mapping[str, Any]],
    *,
    project_mode: str,
    docs_by_id: Mapping[str, str] | None = None,
    max_photos: int = 24,
) -> list:
    """One ask per unresolved photo annotation / vision fact."""
    from orbitbrief_core.pm_handoff.question_engine import (
        QuestionCandidate,
        _atom_evidence_text,
        _atoms_by_id,
        _is_customer_facing_question,
        _photo_meta,
        _source_from_atom,
        _with_evidence,
    )

    atom_list = [a for a in atoms if isinstance(a, Mapping)]
    by_id = _atoms_by_id(atom_list)
    out = []
    seen_region: set[str] = set()
    for atom in atom_list:
        meta = _photo_meta(atom, atoms_by_id=by_id)
        if not meta.get("is_photo") and not meta.get("fact_kind"):
            # Also accept image_* atom types
            atype = str(atom.get("atom_type") or "").lower()
            if not atype.startswith("image") and "photo" not in atype and "annotation" not in atype:
                continue
        kind = str(meta.get("fact_kind") or atom.get("fact_kind") or "annotation").lower()
        if kind not in _PHOTO_FACT_KINDS:
            kind = "annotation"
        region = str(meta.get("region_ref") or atom.get("id") or atom.get("atom_id") or "")
        if region and region in seen_region:
            continue
        if region:
            seen_region.add(region)
        text = _atom_evidence_text(atom)
        if len(text) < 8:
            continue
        # Skip soft aesthetic vibes
        if re.search(r"(?i)\b(?:aesthetic|cleaner\s+look|professional\s+appearance)\b", text):
            continue
        ask = _PHOTO_ASK.get(kind, _PHOTO_ASK["annotation"])
        # Specialize with a short quote stem when useful
        short = re.sub(r"\s+", " ", text).strip()
        if 12 <= len(short) <= 90 and "?" not in short:
            ask = f"Confirm scope for photo evidence: \"{short}\" — approved as annotated?"
        if not _is_customer_facing_question(ask):
            continue
        src = _source_from_atom(
            atom,
            text,
            score=0.9,
            docs_by_id=docs_by_id,
            atoms_by_id=by_id,
        )
        aid = str(atom.get("id") or atom.get("atom_id") or "")
        rid = f"photo.{kind}.{fingerprint_question(text)[:40] or aid[:40] or 'x'}"
        cand = QuestionCandidate(
            rule_id=rid,
            domain_id="field_evidence",
            label=f"Photo — {kind.replace('_', ' ')}",
            severity="warning",
            message="Field photo annotation needs a PM decision before quoting.",
            suggested_open_question=ask,
            observed_summary=f"Photo fact · {kind}",
            source="evidence",
            score=0.8,
            evidence_atom_ids=[aid] if aid else [],
            evidence_sources=[src],
            project_mode=project_mode,
        )
        grounded = _with_evidence(
            cand, atoms=atom_list, docs_by_id=docs_by_id, require=True, min_score=0.35
        )
        if grounded is not None:
            out.append(grounded)
        if len(out) >= max_photos:
            break
    return out


_QTY_CONFLICT_RE = re.compile(
    r"(?i)(?:qty|quantity|count).{0,40}(?:disagree|mismatch|conflict|differ|vs\.?|versus)|"
    r"(?:\d+)\s*(?:x|×)\s*.{0,40}(?:vs\.?|versus|but\s+(?:bom|quote|email)\s+(?:says|shows))"
)


def candidates_from_quantity_conflicts(
    atoms: Iterable[Mapping[str, Any]],
    *,
    project_mode: str,
    envelope: Mapping[str, Any] | None = None,
    docs_by_id: Mapping[str, str] | None = None,
    max_items: int = 12,
) -> list:
    """Ask which quantity is authoritative when sources disagree."""
    from orbitbrief_core.pm_handoff.question_engine import (
        QuestionCandidate,
        _atom_evidence_text,
        _atoms_by_id,
        _is_customer_facing_question,
        _source_from_atom,
        _with_evidence,
    )

    atom_list = [a for a in atoms if isinstance(a, Mapping)]
    out = []
    # Envelope-level contradictions if present
    flags = []
    if isinstance(envelope, Mapping):
        for key in ("quantity_contradictions", "reconciliation_flags", "qty_conflicts"):
            raw = envelope.get(key)
            if isinstance(raw, list):
                flags.extend([x for x in raw if isinstance(x, Mapping)])
    for i, flag in enumerate(flags[:max_items]):
        label = str(flag.get("label") or flag.get("kind") or flag.get("sku") or f"item_{i}")
        q = f"Which quantity is authoritative for {label} — reconcile conflicting source counts before quoting."
        if "?" not in q:
            q = q.rstrip(".") + "?"
        trigger = re.compile(re.escape(label[:32]), re.I) if len(label) >= 3 else _QTY_CONFLICT_RE
        cand = QuestionCandidate(
            rule_id=f"qty.conflict.{fingerprint_question(label)[:40] or i}",
            domain_id="hardware",
            label=f"Quantity conflict — {label[:48]}",
            severity="blocker",
            message="Cross-document quantity disagreement.",
            suggested_open_question=q,
            observed_summary="Quantity contradiction",
            source="evidence",
            score=0.9,
            project_mode=project_mode,
        )
        grounded = _with_evidence(
            cand, atoms=atom_list, trigger=trigger, docs_by_id=docs_by_id, require=True, min_score=0.35
        )
        if grounded is not None:
            out.append(grounded)

    # Atom-level qty conflict language
    seen: set[str] = set()
    for atom in atom_list:
        text = _atom_evidence_text(atom)
        if not _QTY_CONFLICT_RE.search(text):
            continue
        fp = fingerprint_question(text)
        if fp in seen:
            continue
        seen.add(fp)
        q = (
            "Confirm the authoritative quantity where sources disagree: "
            + re.sub(r"\s+", " ", text).strip()[:140]
        )
        if not q.endswith("?"):
            q += "?"
        if not _is_customer_facing_question(q):
            continue
        by_id = _atoms_by_id(atom_list)
        src = _source_from_atom(atom, text, score=0.88, docs_by_id=docs_by_id, atoms_by_id=by_id)
        aid = str(atom.get("id") or atom.get("atom_id") or "")
        out.append(
            QuestionCandidate(
                rule_id=f"qty.atom.{fp[:40]}",
                domain_id="hardware",
                label="Quantity conflict",
                severity="blocker",
                message="Quantity language conflict in source.",
                suggested_open_question=q[:220],
                observed_summary="Quantity conflict atom",
                source="evidence",
                score=0.87,
                evidence_atom_ids=[aid] if aid else [],
                evidence_sources=[src],
                project_mode=project_mode,
            )
        )
        if len(out) >= max_items:
            break
    return out


def candidates_from_open_decisions(
    atoms: Iterable[Mapping[str, Any]],
    *,
    project_mode: str,
    docs_by_id: Mapping[str, str] | None = None,
    max_items: int = 20,
) -> list:
    """Promote clear decision/missing_info atoms that already look like PM asks."""
    from orbitbrief_core.pm_handoff.question_engine import (
        QuestionCandidate,
        _atom_evidence_text,
        _atoms_by_id,
        _is_customer_facing_question,
        _source_from_atom,
    )

    atom_list = [a for a in atoms if isinstance(a, Mapping)]
    by_id = _atoms_by_id(atom_list)
    out = []
    seen: set[str] = set()
    for atom in atom_list:
        atype = str(atom.get("atom_type") or "").lower()
        if atype not in {"decision", "missing_info", "gap", "open_question", "constraint"}:
            continue
        text = _atom_evidence_text(atom)
        if not _is_customer_facing_question(text):
            continue
        if text.count("|") >= 3:
            continue
        # Must already be decision-shaped (not observation + ?)
        if not (
            "?" in text
            or re.match(
                r"(?i)^(?:confirm|which|who|what|when|where|how|decide|clarify)\b",
                text.strip(),
            )
        ):
            continue
        fp = fingerprint_question(text)
        if fp in seen:
            continue
        seen.add(fp)
        q = text.strip()
        if q[0].islower():
            q = q[0].upper() + q[1:]
        src = _source_from_atom(atom, text, score=0.91, docs_by_id=docs_by_id, atoms_by_id=by_id)
        aid = str(atom.get("id") or atom.get("atom_id") or "")
        out.append(
            QuestionCandidate(
                rule_id=f"decision.{atype}.{fp[:40]}",
                domain_id="project",
                label="Open decision",
                severity="blocker" if atype in {"missing_info", "gap"} else "warning",
                message="Decision atom still open in source.",
                suggested_open_question=q[:220],
                observed_summary=f"Decision · {atype}",
                source="evidence",
                score=0.9,
                evidence_atom_ids=[aid] if aid else [],
                evidence_sources=[src],
                project_mode=project_mode,
            )
        )
        if len(out) >= max_items:
            break
    return out


_REAL_ROOM_RE = re.compile(
    r"^(?:KITCHEN|LOBBY(?:\s+LEVEL)?|OFFICE|CLOSET|CORRIDOR|DATA\s+CENTER|"
    r"MDF(?:\s+ROOM)?|IDF|ELEVATOR(?:\s+(?:CAB|LOBBY|MACHINE\s+ROOM))?|"
    r"MEETING(?:\s+STORAGE)?|GUESTROOM|BALLROOM|BOARDROOM|CONFERENCE|"
    r"SERVER\s+ROOM|TELECOM|RISER|STORAGE|MECHANICAL(?:\s+ROOM)?|"
    r"ELECTRICAL(?:\s+ROOM)?|CONTROL\s+ROOM)\b",
    re.I,
)
_STOP_SYMBOLS = frozenset(
    {
        "the", "and", "for", "only", "use", "or", "to", "of", "a", "an", "in", "on",
        "with", "from", "by", "at", "as", "is", "be", "this", "that", "page", "date",
    }
)


def candidates_from_customer_instructions(
    atoms: Iterable[Mapping[str, Any]],
    *,
    project_mode: str,
    docs_by_id: Mapping[str, str] | None = None,
    max_items: int = 12,
) -> list:
    """HubSpot / note instructions that are already PM-shaped."""
    from orbitbrief_core.pm_handoff.question_engine import (
        QuestionCandidate,
        _atom_evidence_text,
        _atoms_by_id,
        _is_customer_facing_question,
        _source_from_atom,
        _with_evidence,
    )

    atom_list = [a for a in atoms if isinstance(a, Mapping)]
    by_id = _atoms_by_id(atom_list)
    out = []
    seen: set[str] = set()
    for atom in atom_list:
        if str(atom.get("atom_type") or "").lower() != "customer_instruction":
            continue
        text = _atom_evidence_text(atom)
        if len(text) < 20:
            continue
        low = text.lower()
        # Rewrite note prose into a Confirm ask.
        if "need to figure" in low or "figure this" in low:
            q = "What open item still needs a decision before we can quote (per customer note)?"
        elif "source hardware" in low or "do not have a contact" in low:
            q = "Who sources AV / access-control / security hardware — customer-furnished or PurTera-furnished?"
        elif "operations early" in low:
            q = "Confirm operations must be involved early for equipment decisions and install logistics."
        elif "mobilization" in low or "conduit" in low:
            q = "Confirm mobilization timing relative to electrician conduit pull (per customer note)."
        else:
            q = "Confirm customer instruction: " + re.sub(r"\s+", " ", text).strip()[:160]
            if not q.endswith("?"):
                q += "?"
        if not _is_customer_facing_question(q):
            continue
        fp = fingerprint_question(q)
        if fp in seen:
            continue
        seen.add(fp)
        src = _source_from_atom(atom, text, score=0.93, docs_by_id=docs_by_id, atoms_by_id=by_id)
        aid = str(atom.get("id") or atom.get("atom_id") or "")
        cand = QuestionCandidate(
            rule_id=f"instruction.{fp[:40]}",
            domain_id="project",
            label="Customer instruction",
            severity="blocker",
            message="Customer note requires a PM decision.",
            suggested_open_question=q[:220],
            observed_summary="Customer instruction",
            source="evidence",
            score=0.94,
            evidence_atom_ids=[aid] if aid else [],
            evidence_sources=[src],
            project_mode=project_mode,
        )
        grounded = _with_evidence(cand, atoms=atom_list, docs_by_id=docs_by_id, require=True)
        if grounded is not None:
            out.append(grounded)
        if len(out) >= max_items:
            break
    return out


def candidates_from_assumptions(
    atoms: Iterable[Mapping[str, Any]],
    *,
    project_mode: str,
    docs_by_id: Mapping[str, str] | None = None,
    max_items: int = 16,
) -> list:
    from orbitbrief_core.pm_handoff.question_engine import (
        QuestionCandidate,
        _atom_evidence_text,
        _atoms_by_id,
        _is_customer_facing_question,
        _source_from_atom,
        _with_evidence,
    )

    atom_list = [a for a in atoms if isinstance(a, Mapping)]
    by_id = _atoms_by_id(atom_list)
    out = []
    seen: set[str] = set()
    for atom in atom_list:
        at = str(atom.get("atom_type") or "").lower()
        if at not in {"assumption", "pricing_assumption"}:
            continue
        text = _atom_evidence_text(atom)
        if len(text) < 24:
            continue
        if at == "assumption" and not re.search(
            r"(?i)\b(?:assume|assumes|assumption|includes|prewired|ofe|owner[\-\s]?furnish)\b",
            text,
        ):
            continue
        if text.count("|") >= 3:
            continue
        # Skip pure rate-card noise
        if re.search(r"(?i)^\s*(?:cost|selll?)\s+rates?\s*:", text):
            continue
        body = re.sub(r"\s+", " ", text).strip()[:160]
        q = f"Confirm pricing assumption is still valid: {body}"
        if not q.endswith("?"):
            q += "?"
        if not _is_customer_facing_question(q):
            continue
        fp = fingerprint_question(body)
        if fp in seen:
            continue
        seen.add(fp)
        src = _source_from_atom(atom, text, score=0.9, docs_by_id=docs_by_id, atoms_by_id=by_id)
        aid = str(atom.get("id") or atom.get("atom_id") or "")
        rid_tail = (aid.replace("atm_", "")[:24] if aid else fp[:32]) or fp[:32]
        cand = QuestionCandidate(
            rule_id=f"assumption.{rid_tail}",
            domain_id="commercial",
            label="Pricing / scope assumption",
            severity="blocker",
            message="Assumption must be confirmed before quoting.",
            suggested_open_question=q[:220],
            observed_summary="Assumption evidence",
            source="evidence",
            score=0.91,
            evidence_atom_ids=[aid] if aid else [],
            evidence_sources=[src],
            project_mode=project_mode,
        )
        grounded = _with_evidence(cand, atoms=atom_list, docs_by_id=docs_by_id, require=True)
        if grounded is not None:
            out.append(grounded)
        if len(out) >= max_items:
            break
    return out


_SCOPE_VERB_RE = re.compile(
    r"(?i)\b(?:assess|assessment|test|testing|review|implement|deploy|install|configure|"
    r"deliver|provide|include|scope|pentest|vulnerab|security|network|application|"
    r"report|remediat|scan|audit|workshop|training|design|migrate|backup|immutable|"
    r"retention|storage|azure|firewall|switch|wireless|access\s+control|camera|"
    r"riser|conduit|cable|rack|cutover|commission)\b"
)
_SCOPE_JUNK_RE = re.compile(
    r"(?i)\b(?:hope my email|excited|regards|thank you|hi\b|hello\b|chat tomorrow|"
    r"www\.|https?://|oppty\s*#|quotation number|director of|nick@)\b"
)


def candidates_from_scope_commitments(
    atoms: Iterable[Mapping[str, Any]],
    *,
    project_mode: str,
    docs_by_id: Mapping[str, str] | None = None,
    max_items: int = 40,
) -> list:
    """Turn substantive scope_item / task / deliverable atoms into Confirm asks."""
    from orbitbrief_core.pm_handoff.question_engine import (
        QuestionCandidate,
        _atom_evidence_text,
        _atoms_by_id,
        _is_customer_facing_question,
        _source_from_atom,
        _with_evidence,
    )

    atom_list = [a for a in atoms if isinstance(a, Mapping)]
    by_id = _atoms_by_id(atom_list)
    out = []
    seen: set[str] = set()
    for atom in atom_list:
        at = str(atom.get("atom_type") or "").lower()
        if at not in {"scope_item", "task", "deliverable", "action_item", "service_line"}:
            continue
        text = _atom_evidence_text(atom)
        if len(text) < 28 or text.count("|") >= 3:
            continue
        if _SCOPE_JUNK_RE.search(text):
            continue
        if not _SCOPE_VERB_RE.search(text):
            continue
        body = re.sub(r"\s+", " ", text).strip()[:150]
        if at == "deliverable":
            q = f"Confirm this deliverable is included in the quote: {body}"
        elif at == "task":
            q = f"Confirm this task is in-scope and scheduled: {body}"
        else:
            q = f"Confirm this is in-scope for the quote: {body}"
        if not q.endswith("?"):
            q += "?"
        if not _is_customer_facing_question(q):
            continue
        # Fingerprint the evidence body (not the shared Confirm stem) so rule_ids stay unique.
        fp = fingerprint_question(body)
        if fp in seen:
            continue
        seen.add(fp)
        src = _source_from_atom(atom, text, score=0.86, docs_by_id=docs_by_id, atoms_by_id=by_id)
        aid = str(atom.get("id") or atom.get("atom_id") or "")
        rid_tail = (aid.replace("atm_", "")[:20] if aid else fp[:28]) or fp[:28]
        cand = QuestionCandidate(
            rule_id=f"scope.{at}.{rid_tail}",
            domain_id="project",
            label=f"Scope — {at.replace('_', ' ')}",
            severity="blocker" if at in {"scope_item", "deliverable"} else "warning",
            message="Scope commitment needs PM confirmation before quoting.",
            suggested_open_question=q[:220],
            observed_summary=f"Scope · {at}",
            source="evidence",
            score=0.84,
            evidence_atom_ids=[aid] if aid else [],
            evidence_sources=[src],
            project_mode=project_mode,
        )
        grounded = _with_evidence(cand, atoms=atom_list, docs_by_id=docs_by_id, require=True)
        if grounded is not None:
            out.append(grounded)
        if len(out) >= max_items:
            break
    return out


def candidates_from_requirements_constraints(
    atoms: Iterable[Mapping[str, Any]],
    *,
    project_mode: str,
    docs_by_id: Mapping[str, str] | None = None,
    max_items: int = 28,
) -> list:
    """Requirement / constraint / exclusion / acceptance asks."""
    from orbitbrief_core.pm_handoff.question_engine import (
        QuestionCandidate,
        _atom_evidence_text,
        _atoms_by_id,
        _is_customer_facing_question,
        _source_from_atom,
        _with_evidence,
    )

    atom_list = [a for a in atoms if isinstance(a, Mapping)]
    by_id = _atoms_by_id(atom_list)
    out = []
    seen: set[str] = set()
    for atom in atom_list:
        at = str(atom.get("atom_type") or "").lower()
        if at not in {
            "requirement",
            "constraint",
            "exclusion",
            "acceptance_criterion",
            "compliance_rule",
            "contract_term",
            "payment_term",
            "change_order_rule",
        }:
            continue
        text = _atom_evidence_text(atom)
        if len(text) < 24 or text.count("|") >= 3:
            continue
        if _SCOPE_JUNK_RE.search(text):
            continue
        body = re.sub(r"\s+", " ", text).strip()[:150]
        if at == "exclusion":
            q = f"Confirm this exclusion stands as written: {body}"
        elif at == "acceptance_criterion":
            q = f"Confirm acceptance criterion for delivery: {body}"
        elif at in {"payment_term", "contract_term", "change_order_rule"}:
            q = f"Confirm commercial term is accepted for this quote: {body}"
        else:
            q = f"Confirm this requirement is binding for the quote: {body}"
        if not q.endswith("?"):
            q += "?"
        if not _is_customer_facing_question(q):
            continue
        fp = fingerprint_question(body)
        if fp in seen:
            continue
        seen.add(fp)
        src = _source_from_atom(atom, text, score=0.88, docs_by_id=docs_by_id, atoms_by_id=by_id)
        aid = str(atom.get("id") or atom.get("atom_id") or "")
        rid_tail = (aid.replace("atm_", "")[:20] if aid else fp[:28]) or fp[:28]
        cand = QuestionCandidate(
            rule_id=f"req.{at}.{rid_tail}",
            domain_id="commercial" if at in {"payment_term", "contract_term"} else "project",
            label=f"{at.replace('_', ' ').title()}",
            severity="blocker" if at in {"requirement", "constraint", "exclusion"} else "warning",
            message="Requirement/constraint needs PM confirmation.",
            suggested_open_question=q[:220],
            observed_summary=f"Requirement · {at}",
            source="evidence",
            score=0.87,
            evidence_atom_ids=[aid] if aid else [],
            evidence_sources=[src],
            project_mode=project_mode,
        )
        grounded = _with_evidence(cand, atoms=atom_list, docs_by_id=docs_by_id, require=True)
        if grounded is not None:
            out.append(grounded)
        if len(out) >= max_items:
            break
    return out


def candidates_from_risks(
    atoms: Iterable[Mapping[str, Any]],
    *,
    project_mode: str,
    docs_by_id: Mapping[str, str] | None = None,
    max_items: int = 20,
) -> list:
    """Risk atoms → how we treat / mitigate in the quote (never raw table rows)."""
    from orbitbrief_core.pm_handoff.question_engine import (
        QuestionCandidate,
        _atom_evidence_text,
        _atoms_by_id,
        _is_customer_facing_question,
        _source_from_atom,
        _with_evidence,
    )

    atom_list = [a for a in atoms if isinstance(a, Mapping)]
    by_id = _atoms_by_id(atom_list)
    out = []
    seen: set[str] = set()
    for atom in atom_list:
        if str(atom.get("atom_type") or "").lower() != "risk":
            continue
        text = _atom_evidence_text(atom)
        if len(text) < 32 or text.count("|") >= 3:
            continue
        if re.search(r"\|\s*r\d+\s*\|", text, re.I):
            continue
        if _SCOPE_JUNK_RE.search(text):
            continue
        # Skip bare OWASP title stubs
        if len(text) < 48 and not re.search(r"[.:,;]", text):
            continue
        body = re.sub(r"\s+", " ", text).strip()[:150]
        q = f"Confirm how this risk is handled in the quote / SOW: {body}"
        if not q.endswith("?"):
            q += "?"
        if not _is_customer_facing_question(q):
            continue
        fp = fingerprint_question(body)
        if fp in seen:
            continue
        seen.add(fp)
        src = _source_from_atom(atom, text, score=0.83, docs_by_id=docs_by_id, atoms_by_id=by_id)
        aid = str(atom.get("id") or atom.get("atom_id") or "")
        rid_tail = (aid.replace("atm_", "")[:20] if aid else fp[:28]) or fp[:28]
        cand = QuestionCandidate(
            rule_id=f"risk.treat.{rid_tail}",
            domain_id="project",
            label="Risk treatment",
            severity="warning",
            message="Risk needs explicit quote/SOW treatment.",
            suggested_open_question=q[:220],
            observed_summary="Risk atom",
            source="evidence",
            score=0.81,
            evidence_atom_ids=[aid] if aid else [],
            evidence_sources=[src],
            project_mode=project_mode,
        )
        grounded = _with_evidence(cand, atoms=atom_list, docs_by_id=docs_by_id, require=True)
        if grounded is not None:
            out.append(grounded)
        if len(out) >= max_items:
            break
    return out


def candidates_from_keyed_notes(
    atoms: Iterable[Mapping[str, Any]],
    *,
    project_mode: str,
    docs_by_id: Mapping[str, str] | None = None,
    max_items: int = 28,
) -> list:
    """Site implementation keyed notes → confirm coordination."""
    from orbitbrief_core.pm_handoff.question_engine import (
        QuestionCandidate,
        _atom_evidence_text,
        _atoms_by_id,
        _is_customer_facing_question,
        _source_from_atom,
        _with_evidence,
    )

    atom_list = [a for a in atoms if isinstance(a, Mapping)]
    by_id = _atoms_by_id(atom_list)
    out = []
    seen: set[str] = set()
    for atom in atom_list:
        at = str(atom.get("atom_type") or "").lower()
        text = _atom_evidence_text(atom)
        if at not in {"site_implementation_note", "scope_item", "requirement"}:
            continue
        if not re.search(r"(?i)keyed\s+notes?|coordinate\s+location|provide\s+\(\d+\)|home\s+run|conduit", text):
            continue
        body = re.sub(r"\s+", " ", text).strip()
        body = re.sub(r"(?i)^keyed\s+notes?:\s*", "", body)[:160]
        if len(body) < 20:
            continue
        q = f"Confirm keyed-note scope is in quote: {body}"
        if not q.endswith("?"):
            q += "?"
        if not _is_customer_facing_question(q):
            continue
        fp = fingerprint_question(q)
        if fp in seen:
            continue
        seen.add(fp)
        src = _source_from_atom(atom, text, score=0.89, docs_by_id=docs_by_id, atoms_by_id=by_id)
        aid = str(atom.get("id") or atom.get("atom_id") or "")
        cand = QuestionCandidate(
            rule_id=f"keyed.{fp[:40]}",
            domain_id="field_evidence",
            label="Keyed note coordination",
            severity="warning",
            message="Drawing keyed note needs quote confirmation.",
            suggested_open_question=q[:220],
            observed_summary="Keyed note",
            source="evidence",
            score=0.88,
            evidence_atom_ids=[aid] if aid else [],
            evidence_sources=[src],
            project_mode=project_mode,
        )
        grounded = _with_evidence(cand, atoms=atom_list, docs_by_id=docs_by_id, require=True)
        if grounded is not None:
            out.append(grounded)
        if len(out) >= max_items:
            break
    return out


def candidates_from_schematic_warnings(
    atoms: Iterable[Mapping[str, Any]],
    *,
    project_mode: str,
    docs_by_id: Mapping[str, str] | None = None,
    max_items: int = 28,
) -> list:
    """Actionable schematic warnings (legend ambiguity / real unknown symbols)."""
    from orbitbrief_core.pm_handoff.question_engine import (
        QuestionCandidate,
        _atom_evidence_text,
        _atoms_by_id,
        _is_customer_facing_question,
        _source_from_atom,
        _with_evidence,
    )

    atom_list = [a for a in atoms if isinstance(a, Mapping)]
    by_id = _atoms_by_id(atom_list)
    out = []
    seen: set[str] = set()
    for atom in atom_list:
        if str(atom.get("atom_type") or "").lower() != "schematic_warning":
            continue
        loc = atom.get("locator") if isinstance(atom.get("locator"), Mapping) else {}
        wtype = str((loc or {}).get("warning_type") or "").lower()
        text = _atom_evidence_text(atom)
        sheet = str((loc or {}).get("sheet_number") or "")
        page = (loc or {}).get("page")
        token_m = re.search(r"Token '([^']+)'", text)
        token = (token_m.group(1) if token_m else "").strip()
        if wtype == "unknown_symbol":
            if not token or token.lower() in _STOP_SYMBOLS or len(token) < 2:
                continue
            # Skip pure English stop-ish OCR garbage
            if token.isalpha() and token.upper() in {"THE", "AND", "FOR", "ONLY", "USE", "SHEET"}:
                continue
            q = (
                f"Confirm schematic symbol '{token}' on sheet {sheet or page} — "
                f"what device/outlet does it represent for the quote?"
            )
        elif wtype == "ambiguous_legend_reference":
            q = (
                f"Resolve ambiguous legend reference on sheet {sheet or page}: "
                f"{re.sub(r'\\s+', ' ', text).strip()[:120]}"
            )
            if not q.endswith("?"):
                q += "?"
        else:
            continue
        if not _is_customer_facing_question(q):
            continue
        fp = fingerprint_question(q)
        if fp in seen:
            continue
        seen.add(fp)
        src = _source_from_atom(atom, text, score=0.86, docs_by_id=docs_by_id, atoms_by_id=by_id)
        aid = str(atom.get("id") or atom.get("atom_id") or "")
        cand = QuestionCandidate(
            rule_id=f"schematic.warn.{wtype}.{fp[:32]}",
            domain_id="field_evidence",
            label="Schematic legend / symbol",
            severity="warning",
            message="Drawing legend ambiguity blocks accurate BOM mapping.",
            suggested_open_question=q[:220],
            observed_summary=f"Schematic warning · {wtype}",
            source="evidence",
            score=0.85,
            evidence_atom_ids=[aid] if aid else [],
            evidence_sources=[src],
            project_mode=project_mode,
        )
        grounded = _with_evidence(cand, atoms=atom_list, docs_by_id=docs_by_id, require=True)
        if grounded is not None:
            out.append(grounded)
        if len(out) >= max_items:
            break
    return out


def candidates_from_schematic_rooms(
    atoms: Iterable[Mapping[str, Any]],
    *,
    project_mode: str,
    docs_by_id: Mapping[str, str] | None = None,
    max_rooms: int = 24,
) -> list:
    """Per real room: confirm AV/data outlet scope from schematic room labels."""
    from orbitbrief_core.pm_handoff.question_engine import (
        QuestionCandidate,
        _atom_evidence_text,
        _atoms_by_id,
        _is_customer_facing_question,
        _source_from_atom,
        _with_evidence,
    )

    atom_list = [a for a in atoms if isinstance(a, Mapping)]
    by_id = _atoms_by_id(atom_list)
    out = []
    seen_rooms: set[str] = set()
    for atom in atom_list:
        if str(atom.get("atom_type") or "").lower() != "schematic_room":
            continue
        text = _atom_evidence_text(atom)
        m = re.search(r"Room '([^']+)'", text)
        if not m:
            continue
        room = m.group(1).strip()
        if not _REAL_ROOM_RE.search(room):
            continue
        key = room.upper()
        if key in seen_rooms:
            continue
        seen_rooms.add(key)
        loc = atom.get("locator") if isinstance(atom.get("locator"), Mapping) else {}
        sheet = str((loc or {}).get("sheet_number") or "")
        q = (
            f"Confirm in-scope devices / outlets for room '{room}'"
            + (f" on sheet {sheet}" if sheet else "")
            + " — what is quoted vs OFE?"
        )
        if not _is_customer_facing_question(q):
            continue
        src = _source_from_atom(atom, text, score=0.84, docs_by_id=docs_by_id, atoms_by_id=by_id)
        aid = str(atom.get("id") or atom.get("atom_id") or "")
        rid = f"room.{re.sub(r'[^\\w]+', '_', room.lower())[:40]}"
        cand = QuestionCandidate(
            rule_id=rid,
            domain_id="audio_visual" if project_mode == "av_install" else "site",
            label=f"Room scope — {room}",
            severity="warning",
            message="Schematic room needs quoted device/outlet confirmation.",
            suggested_open_question=q,
            observed_summary=f"Schematic room · {room}",
            source="evidence",
            score=0.83,
            evidence_atom_ids=[aid] if aid else [],
            evidence_sources=[src],
            project_mode=project_mode,
        )
        grounded = _with_evidence(cand, atoms=atom_list, docs_by_id=docs_by_id, require=True)
        if grounded is not None:
            out.append(grounded)
        if len(out) >= max_rooms:
            break
    return out


def candidates_from_bom_lines(
    atoms: Iterable[Mapping[str, Any]],
    *,
    project_mode: str,
    docs_by_id: Mapping[str, str] | None = None,
    max_items: int = 22,
) -> list:
    """Confirm BOM lines that look incomplete / TBD."""
    from orbitbrief_core.pm_handoff.question_engine import (
        QuestionCandidate,
        _atom_evidence_text,
        _atoms_by_id,
        _is_customer_facing_question,
        _source_from_atom,
        _with_evidence,
    )

    atom_list = [a for a in atoms if isinstance(a, Mapping)]
    by_id = _atoms_by_id(atom_list)
    out = []
    seen: set[str] = set()
    for atom in atom_list:
        at = str(atom.get("atom_type") or "").lower()
        if at not in {"bom_line", "vendor_line_item", "quantity", "service_line"}:
            continue
        text = _atom_evidence_text(atom)
        if len(text) < 12:
            continue
        # Prefer lines that look uncertain or high-impact
        if not re.search(
            r"(?i)\b(?:tbd|allowance|optional|alternate|or\s+equal|nic|ofe|qty|each|lot)\b|\d+",
            text,
        ):
            continue
        body = re.sub(r"\s+", " ", text).strip()[:140]
        q = f"Confirm BOM line is in this quote as written: {body}?"
        if not _is_customer_facing_question(q):
            continue
        fp = fingerprint_question(body)
        if fp in seen:
            continue
        seen.add(fp)
        src = _source_from_atom(atom, text, score=0.82, docs_by_id=docs_by_id, atoms_by_id=by_id)
        aid = str(atom.get("id") or atom.get("atom_id") or "")
        rid_tail = (aid.replace("atm_", "")[:24] if aid else fp[:32]) or fp[:32]
        cand = QuestionCandidate(
            rule_id=f"bom.{rid_tail}",
            domain_id="hardware",
            label="BOM confirmation",
            severity="warning",
            message="BOM line needs PM confirmation.",
            suggested_open_question=q[:220],
            observed_summary="BOM line",
            source="evidence",
            score=0.8,
            evidence_atom_ids=[aid] if aid else [],
            evidence_sources=[src],
            project_mode=project_mode,
        )
        grounded = _with_evidence(cand, atoms=atom_list, docs_by_id=docs_by_id, require=True)
        if grounded is not None:
            out.append(grounded)
        if len(out) >= max_items:
            break
    return out


def build_extended_candidates(
    *,
    sites: list[SiteSummary],
    atoms: Iterable[Mapping[str, Any]],
    project_mode: str,
    blob: str,
    envelope: Mapping[str, Any] | None = None,
    docs_by_id: Mapping[str, str] | None = None,
) -> list:
    """All evidence-derived generators for the ~50 pool."""
    from orbitbrief_core.pm_handoff.question_engine import _docs_by_artifact_id

    docs = docs_by_id or _docs_by_artifact_id(envelope if isinstance(envelope, Mapping) else None)
    atom_list = [a for a in atoms if isinstance(a, Mapping)]
    out = []
    out.extend(
        candidates_from_customer_instructions(
            atom_list, project_mode=project_mode, docs_by_id=docs
        )
    )
    out.extend(
        candidates_from_assumptions(
            atom_list, project_mode=project_mode, docs_by_id=docs
        )
    )
    out.extend(
        candidates_from_keyed_notes(
            atom_list, project_mode=project_mode, docs_by_id=docs
        )
    )
    out.extend(
        candidates_from_scope_commitments(
            atom_list, project_mode=project_mode, docs_by_id=docs
        )
    )
    out.extend(
        candidates_from_requirements_constraints(
            atom_list, project_mode=project_mode, docs_by_id=docs
        )
    )
    out.extend(
        candidates_from_risks(
            atom_list, project_mode=project_mode, docs_by_id=docs
        )
    )
    out.extend(
        candidates_from_schematic_warnings(
            atom_list, project_mode=project_mode, docs_by_id=docs
        )
    )
    out.extend(
        candidates_from_schematic_rooms(
            atom_list, project_mode=project_mode, docs_by_id=docs
        )
    )
    out.extend(
        candidates_from_bom_lines(
            atom_list, project_mode=project_mode, docs_by_id=docs
        )
    )
    out.extend(
        candidates_from_sites(
            sites, atoms=atom_list, project_mode=project_mode, blob=blob, docs_by_id=docs
        )
    )
    out.extend(
        candidates_from_photo_facts(
            atom_list, project_mode=project_mode, docs_by_id=docs
        )
    )
    out.extend(
        candidates_from_quantity_conflicts(
            atom_list, project_mode=project_mode, envelope=envelope, docs_by_id=docs
        )
    )
    out.extend(
        candidates_from_open_decisions(
            atom_list, project_mode=project_mode, docs_by_id=docs
        )
    )
    return out
