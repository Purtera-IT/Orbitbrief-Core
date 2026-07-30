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
        # Never promote URL / tracking-link "conflicts"
        if re.search(r"(?i)https?://|hs-sales-engage|hubspot|/ctc/", text):
            continue
        if len(re.sub(r"\W+", "", text)) < 24:
            continue
        fp = fingerprint_question(text)
        if fp in seen:
            continue
        seen.add(fp)
        body = re.sub(r"\s+", " ", text).strip()
        body = re.sub(r"https?://\S+", "", body).strip()
        body = re.sub(r"(?i)\bdevice\s+\w+\s*$", "", body).strip()
        body = re.sub(r"(?i)^\d+\.\s*", "", body).strip()
        body = re.sub(r"(?i)^quantity conflict\s*\(?", "", body).strip(" )")
        body = body[:70].rstrip(".,;:")
        if len(body) < 12:
            continue
        q = f"Where quantities disagree for {body}, which source is authoritative for this quote?"
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


def _clean_decision_text(text: str) -> str:
    from orbitbrief_core.pm_handoff.pm_ask_rewrite import is_unusable_evidence_text

    if is_unusable_evidence_text(text):
        return ""
    q = re.sub(r"[*_`]+", "", text or "")
    q = re.sub(r"\s+", " ", q).strip(" \t-•*")
    # Drop trailing entity tags like "device access point"
    q = re.sub(r"(?i)\s+device\s+[a-z][a-z\s]{0,40}$", "", q).strip()
    # Drop trailing unfinished clauses
    q = re.sub(r"(?i)\s+(?:we have a hybrid sync from).*$", "", q).strip()
    if "?" in q:
        q = q.split("?", 1)[0].strip() + "?"
    if len(q) > 160 or len(q) < 18:
        return ""
    if q and q[0].islower():
        q = q[0].upper() + q[1:]
    return q


def candidates_from_open_decisions(
    atoms: Iterable[Mapping[str, Any]],
    *,
    project_mode: str,
    docs_by_id: Mapping[str, str] | None = None,
    max_items: int = 20,
) -> list:
    """Promote clear decision/missing_info atoms that already look like PM asks."""
    from orbitbrief_core.pm_handoff.pm_ask_rewrite import rewrite_instruction
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
        if text.count("|") >= 3:
            continue
        # Prefer a rewritten sharp ask when patterns match.
        q = rewrite_instruction(text) or _clean_decision_text(text)
        if not q or not _is_customer_facing_question(q):
            continue
        if not (
            "?" in q
            or re.match(
                r"(?i)^(?:confirm|which|who|what|when|where|how|decide|clarify|is|do|does|are|can)\b",
                q.strip(),
            )
        ):
            continue
        if len(q) > 180:
            continue
        fp = fingerprint_question(q)
        if fp in seen:
            continue
        seen.add(fp)
        src = _source_from_atom(atom, text, score=0.91, docs_by_id=docs_by_id, atoms_by_id=by_id)
        aid = str(atom.get("id") or atom.get("atom_id") or "")
        out.append(
            QuestionCandidate(
                rule_id=f"decision.{atype}.{fp[:40]}",
                domain_id="project",
                label="Open decision",
                severity="blocker" if atype in {"missing_info", "gap"} else "warning",
                message="Decision atom still open in source.",
                suggested_open_question=q[:200],
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
    blob: str = "",
    sites: list | None = None,
    max_items: int = 12,
) -> list:
    """HubSpot / note instructions → rewritten PM asks (never paste)."""
    from orbitbrief_core.pm_handoff.pm_ask_rewrite import (
        extract_site_names,
        inject_site_anchor,
        rewrite_instruction,
    )
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
    site_names = extract_site_names(blob or "", sites=sites)
    out = []
    seen: set[str] = set()
    for atom in atom_list:
        if str(atom.get("atom_type") or "").lower() != "customer_instruction":
            continue
        text = _atom_evidence_text(atom)
        if len(text) < 20:
            continue
        q = rewrite_instruction(text)
        if q:
            q = inject_site_anchor(q, site_names, blob=blob or "")
        if not q or not _is_customer_facing_question(q):
            continue
        fp = fingerprint_question(q)
        if fp in seen:
            continue
        seen.add(fp)
        src = _source_from_atom(atom, text, score=0.93, docs_by_id=docs_by_id, atoms_by_id=by_id)
        aid = str(atom.get("id") or atom.get("atom_id") or "")
        rid_tail = (aid.replace("atm_", "")[:24] if aid else fp[:32]) or fp[:32]
        cand = QuestionCandidate(
            rule_id=f"instruction.{rid_tail}",
            domain_id="project",
            label="Customer instruction",
            severity="blocker",
            message="Customer note requires a PM decision.",
            suggested_open_question=q[:200],
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
    blob: str = "",
    sites: list | None = None,
    max_items: int = 16,
) -> list:
    from orbitbrief_core.pm_handoff.pm_ask_rewrite import extract_site_names, rewrite_assumption
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
    site_names = extract_site_names(blob or "", sites=sites)
    out = []
    seen: set[str] = set()
    for atom in atom_list:
        at = str(atom.get("atom_type") or "").lower()
        if at not in {"assumption", "pricing_assumption"}:
            continue
        text = _atom_evidence_text(atom)
        if len(text) < 24 or text.count("|") >= 3:
            continue
        q = rewrite_assumption(text, site_names=site_names, blob=blob or "")
        if not q or not _is_customer_facing_question(q):
            continue
        fp = fingerprint_question(q)
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
            suggested_open_question=q[:200],
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
    blob: str = "",
    sites: list | None = None,
    max_items: int = 40,
) -> list:
    """Turn substantive scope_item / task / deliverable atoms into sharp PM asks."""
    from orbitbrief_core.pm_handoff.pm_ask_rewrite import extract_site_names, rewrite_scope
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
    site_names = extract_site_names(blob or "", sites=sites)
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
        q = rewrite_scope(text, at, project_mode=project_mode, site_names=site_names, blob=blob or "")
        if not q or not _is_customer_facing_question(q):
            continue
        fp = fingerprint_question(q)
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
            suggested_open_question=q[:200],
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
    blob: str = "",
    sites: list | None = None,
    max_items: int = 28,
) -> list:
    """Requirement / constraint / exclusion / acceptance → sharp PM asks."""
    from orbitbrief_core.pm_handoff.pm_ask_rewrite import (
        extract_site_names,
        inject_site_anchor,
        rewrite_requirement,
    )
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
        q = rewrite_requirement(text, at)
        if q:
            q = inject_site_anchor(
                q, extract_site_names(blob or "", sites=sites), blob=blob or ""
            )
        if not q or not _is_customer_facing_question(q):
            continue
        fp = fingerprint_question(q)
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
            suggested_open_question=q[:200],
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
    from orbitbrief_core.pm_handoff.pm_ask_rewrite import rewrite_risk
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
        q = rewrite_risk(text)
        if not q or not _is_customer_facing_question(q):
            continue
        fp = fingerprint_question(q)
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
            suggested_open_question=q[:200],
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


def candidates_from_pm_coverage(
    atoms: Iterable[Mapping[str, Any]],
    *,
    project_mode: str,
    blob: str,
    sites: list | None = None,
    docs_by_id: Mapping[str, str] | None = None,
) -> list:
    """Deal-specific PM coverage — naked templates are suppressed."""
    from orbitbrief_core.pm_handoff.pm_ask_rewrite import (
        extract_site_names,
        specialize_coverage_question,
    )
    from orbitbrief_core.pm_handoff.question_engine import (
        QuestionCandidate,
        _is_customer_facing_question,
        _with_evidence,
    )

    atom_list = [a for a in atoms if isinstance(a, Mapping)]
    hay = blob or ""
    site_names = extract_site_names(hay, sites=sites)
    # Coverage families (domain used for GapCard labeling)
    specs: tuple[tuple[str, str, str, str, float], ...] = (
        ("site_list_lock", "site", "Authoritative site list", "blocker", 0.88),
        ("onsite_contact", "site", "Day-of onsite contact", "blocker", 0.86),
        ("access_badging", "site", "Access / escort / badging", "blocker", 0.87),
        ("work_hours", "site", "Approved work window", "warning", 0.82),
        ("hardware_furnish", "hardware", "CF vs OFE hardware", "blocker", 0.89),
        ("pathway_ownership", "field_evidence", "Pathway ownership", "blocker", 0.88),
        ("acceptance", "project", "Acceptance sign-off", "blocker", 0.85),
        ("payment_gate", "commercial", "Payment / deposit gate", "warning", 0.8),
        ("change_order", "commercial", "Change-order path", "warning", 0.8),
        ("qty_lock", "hardware", "Quantity conflict", "blocker", 0.9),
        ("first_site", "site", "First site / sequence", "warning", 0.83),
        ("exclusions", "commercial", "Exclusion acknowledged", "warning", 0.8),
        ("wireless_design", "wireless", "Wireless design inputs", "blocker", 0.9),
        ("av_keep_remove", "audio_visual", "AV keep vs remove", "blocker", 0.9),
        ("security_roe", "project", "Security ROE", "blocker", 0.91),
    )
    out = []
    for suffix, domain, label, severity, score in specs:
        question = specialize_coverage_question(
            suffix, blob=hay, project_mode=project_mode, site_names=site_names
        )
        if not question or not _is_customer_facing_question(question):
            continue
        # Ground with a tighter trigger derived from the specialized ask tokens
        trig_bits = [w for w in re.findall(r"[a-zA-Z]{4,}", question)[:8]]
        trig = re.compile("|".join(re.escape(t) for t in trig_bits) or r"scope", re.I)
        cand = QuestionCandidate(
            rule_id=f"pmcover.{suffix}",
            domain_id=domain,
            label=label,
            severity=severity,
            message=f"PM coverage — {label}",
            suggested_open_question=question,
            observed_summary=f"PM coverage · {suffix}",
            source="evidence",
            # Slightly below mode/evidence-specific so ranking prefers deal-locked asks
            score=score,
            project_mode=project_mode,
        )
        grounded = _with_evidence(
            cand,
            atoms=atom_list,
            trigger=trig,
            docs_by_id=docs_by_id,
            require=True,
            min_score=0.34,
        )
        if grounded is not None:
            out.append(grounded)
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
        if not re.search(r"(?i)keyed\s+notes?|coordinate\s+location|provide\s+\(\d+\)|home\s+run|conduit|pack(?:ing)?\s*/?\s*prep|inventory\s+verification|de[\-\s]?rack|iron\s+mountain|power\s+down\s+equipment", text):
            continue
        body = re.sub(r"\s+", " ", text).strip()
        body = re.sub(r"(?i)^keyed\s+notes?:\s*", "", body)
        # Collapse pipe-joined near-duplicates before quoting.
        body = re.sub(r"\s*\|\|.*", "", body).strip()
        body = body[:90]
        if len(body) < 20:
            continue
        from orbitbrief_core.pm_handoff.pm_ask_rewrite import rewrite_scope

        # Prefer sharp rewrite on the full note text (truncated body loses anchors).
        q = rewrite_scope(text, "scope_item", project_mode=project_mode) or (
            f"Is this keyed-note work in the quote — coordinate now or exclude: \"{body}\"?"
        )
        if not _is_customer_facing_question(q):
            continue
        # Coarse stem so "DATA DROP FOR X" / "DATA DROP FOR Y" still near-dedupe via family.
        fp = fingerprint_question(re.sub(r"\b[A-Z0-9]{1,4}\b", "x", body)[:48])
        if fp in seen:
            continue
        seen.add(fp)
        src = _source_from_atom(atom, text, score=0.89, docs_by_id=docs_by_id, atoms_by_id=by_id)
        aid = str(atom.get("id") or atom.get("atom_id") or "")
        rid_tail = (aid.replace("atm_", "")[:24] if aid else fp[:32]) or fp[:32]
        cand = QuestionCandidate(
            rule_id=f"keyed.{rid_tail}",
            domain_id="field_evidence",
            label="Keyed note coordination",
            severity="warning",
            message="Drawing keyed note needs quote confirmation.",
            suggested_open_question=q[:200],
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
        from orbitbrief_core.pm_handoff.pm_ask_rewrite import rewrite_bom

        q = rewrite_bom(text)
        if not q or not _is_customer_facing_question(q):
            continue
        fp = fingerprint_question(q)
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
            suggested_open_question=q[:200],
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
    # Specialized PM coverage (naked templates suppressed inside).
    out.extend(
        candidates_from_pm_coverage(
            atom_list,
            project_mode=project_mode,
            blob=blob,
            sites=sites,
            docs_by_id=docs,
        )
    )
    out.extend(
        candidates_from_customer_instructions(
            atom_list,
            project_mode=project_mode,
            docs_by_id=docs,
            blob=blob,
            sites=sites,
        )
    )
    out.extend(
        candidates_from_assumptions(
            atom_list,
            project_mode=project_mode,
            docs_by_id=docs,
            blob=blob,
            sites=sites,
        )
    )
    out.extend(
        candidates_from_keyed_notes(
            atom_list, project_mode=project_mode, docs_by_id=docs
        )
    )
    out.extend(
        candidates_from_scope_commitments(
            atom_list,
            project_mode=project_mode,
            docs_by_id=docs,
            blob=blob,
            sites=sites,
        )
    )
    out.extend(
        candidates_from_requirements_constraints(
            atom_list,
            project_mode=project_mode,
            docs_by_id=docs,
            blob=blob,
            sites=sites,
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
