"""Evidence-first customer question engine.

Pack YAML checklists answer "what does a complete SOW usually need?"
This module answers "what does **this** deal still need a human to decide?"

Pipeline (product order):
  1. Detect project_mode from evidence + routing
  2. Evidence-first candidates (open_question / decision / risk atoms +
     mode templates gated by evidence)
  3. Answer suppression (sites / BOM / scope already settle it)
  4. PM feedback (dismiss / wrong_for_project / edit / gold add)
  5. Rank + cap (~5–8)
  6. YAML pack gaps only as a rare safety-net for mode-compatible blockers
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from orbitbrief_core.pm_handoff.business_labels import SEVERITY_SORT, domain_label
from orbitbrief_core.pm_handoff.models import GapCard, SiteSummary
from orbitbrief_core.pm_handoff.question_feedback import (
    FeedbackPolicy,
    QuestionFeedbackEvent,
    compile_feedback_policy,
    fingerprint_question,
    load_feedback,
)
from orbitbrief_core.pm_handoff.semantic_dedupe import (
    cosine_similarity,
    evidence_relevance_scores,
    is_near_duplicate_of_any,
    is_neural_embedder,
    resolve_question_embedder,
    semantic_dedupe,
)
from orbitbrief_core.validator.sow_completeness import (
    _NETWORK_INSTALL_EVIDENCE_RE,
    _atom_text,
)

DEFAULT_QUESTION_CAP = 6
MIN_SAFETY_NET_IF_EMPTY = 2
# Drop candidates whose neural relevance to deal evidence falls below this.
NEURAL_RELEVANCE_FLOOR = float(
    __import__("os").environ.get("ORBITBRIEF_QUESTION_NEURAL_FLOOR", "0.28")
)

# ── project modes ─────────────────────────────────────────────────────

MODE_NETWORK_EDGE_INSTALL = "network_edge_install"
MODE_NETWORK_OPS = "network_ops"
MODE_WIRELESS_INSTALL = "wireless_install"
MODE_WIRELESS_CONFIG = "wireless_config"
MODE_CABLING = "cabling_install"
MODE_ALM = "alm"
MODE_STAFF_AUG = "staff_aug"
MODE_AV = "av_install"
MODE_ACCESS = "access_control"
MODE_GENERIC = "generic"

# YAML domain_ids allowed as safety-net per mode (blockers only, rare).
_MODE_YAML_ALLOW: dict[str, frozenset[str]] = {
    MODE_NETWORK_EDGE_INSTALL: frozenset({"global", "commercial", "hardware"}),
    MODE_NETWORK_OPS: frozenset({"global", "commercial", "network_maintenance", "hardware"}),
    MODE_WIRELESS_INSTALL: frozenset({"global", "commercial", "wireless", "hardware"}),
    MODE_WIRELESS_CONFIG: frozenset({"global", "commercial", "wireless"}),
    MODE_CABLING: frozenset({"global", "commercial", "low_voltage_cabling", "hardware"}),
    MODE_ALM: frozenset({"global", "commercial", "alm"}),
    MODE_STAFF_AUG: frozenset({"global", "commercial", "staff_augmentation"}),
    MODE_AV: frozenset({"global", "commercial", "audio_visual", "hardware"}),
    MODE_ACCESS: frozenset({"global", "commercial", "access_control", "hardware"}),
    MODE_GENERIC: frozenset({"global", "commercial"}),
}


def domain_ids_allowed_for_mode(project_mode: str) -> frozenset[str] | None:
    """Return the domain allowlist for a concrete project mode, or None to keep all.

    ``generic`` / unknown modes intentionally return None so we do not strip
    legitimate pack gaps when mode detection is weak. Concrete modes (AV,
    cabling, wireless, …) return the same allowlist used by the YAML safety
    net so VMS / structured-cabling leftovers cannot pollute an AV handoff.
    """
    mode = (project_mode or "").strip()
    if not mode or mode == MODE_GENERIC:
        return None
    return _MODE_YAML_ALLOW.get(mode)

# Ops / ALM / staff families that must never promote on edge-install deals.
_INSTALL_BANNED_RULE_PREFIXES = (
    "network_maintenance.firmware",
    "network_maintenance.coverage",
    "network_maintenance.patch",
    "network_maintenance.oem",
    "network_maintenance.vlan_port_audit",
    "network_maintenance.circuit_demarc",
    "network_maintenance.routing_failover",
    "network_maintenance.port_vlan_wan",
    "network_maintenance.device_inventory",
    "alm.",
    "staff_augmentation.",
)

# Strong WLAN install language only. Bare "WiFi" in a vendor capability matrix
# (e.g. PurTera marketing email) must NOT flip a conference-room AV deal to
# wireless_install — that produced Catalyst's false "AP count/model" blocker.
_WIRELESS_STRONG_RE = re.compile(
    r"\b(?:"
    r"access\s+points?|"
    r"wlan\s+(?:controller|install|deployment|design|survey)|"
    r"wireless\s+(?:ap|access\s+point|install|survey|design|controller)|"
    r"ssid|heatmap|ap[\-\s]?on[\-\s]?a[\-\s]?stick|802\.11(?:ac|ax|be|n|g)?"
    r")\b",
    re.I,
)
_WIRELESS_WEAK_RE = re.compile(
    r"\b(?:wifi|wi[\-\s]?fi|wlan|aps?)\b",
    re.I,
)
# Back-compat alias used by older tests / callers.
_WIRELESS_INSTALL_RE = _WIRELESS_STRONG_RE
_CABLING_RE = re.compile(
    r"\b(?:cat\s?[56]a?|fiber|fibre|drop(?:s)?|cable\s+pull|permanent\s+link|fluke|tia[\-\s]?568)\b",
    re.I,
)
_ALM_RE = re.compile(
    r"\b(?:application\s+lifecycle|release\s+train|change\s+advisory|environment\s+promotion|devops\s+pipeline)\b",
    re.I,
)
_STAFF_AUG_RE = re.compile(
    r"\b(?:staff\s+aug(?:mentation)?|resource\s+surge|1099|cleared\s+resource|badged\s+resource)\b",
    re.I,
)
_AV_RE = re.compile(
    r"\b(?:"
    r"audio[\-\s]?visual|audiovisual|"
    r"projector|dsp\b|crestron|extron|biamp|q[\-\s]?sys|"
    r"conference\s+room(?:\s+av)?|huddle\s+room|teams\s+room|zoom\s+room|"
    r"neat\b|yealink|poly(?:com)?\b|soundbar|hdmi|vesa|"
    r"video\s+codec|room\s+bar|uc\s+bar|display\s+mount"
    r")\b",
    re.I,
)
# Dense AV install evidence — beats a stray marketing WiFi mention.
_AV_STRONG_RE = re.compile(
    r"\b(?:"
    r"neat\b|yealink|teams\s+room|zoom\s+room|huddle\s+room|"
    r"conference\s+room|soundbar|vesa|hdmi\s+over\s+ethernet|"
    r"hdmi\s+replicator|behind\s+the\s+wall|room\s+bar"
    r")\b",
    re.I,
)
_ACCESS_RE = re.compile(
    r"\b(?:access\s+control|card\s+reader|door\s+controller|maglock|electric\s+strike)\b",
    re.I,
)
_CONFIG_ONLY_RE = re.compile(
    r"\b(?:config(?:uration)?[\-\s]?only|license[\-\s]?only|no\s+install|dashboard\s+config)\b",
    re.I,
)


@dataclass
class QuestionCandidate:
    rule_id: str
    domain_id: str
    label: str
    severity: str
    message: str
    suggested_open_question: str
    observed_summary: str = ""
    source: str = "evidence"  # evidence | mode_template | yaml_safety | pm_gold
    score: float = 0.0
    evidence_atom_ids: list[str] = field(default_factory=list)
    evidence_sources: list[dict[str, Any]] = field(default_factory=list)
    project_mode: str = ""

    def to_gap_card(self) -> GapCard:
        return GapCard(
            rule_id=self.rule_id,
            domain_id=self.domain_id,
            domain_label=domain_label(self.domain_id),
            label=self.label,
            severity=self.severity,
            message=self.message,
            suggested_open_question=self.suggested_open_question,
            observed_summary=self.observed_summary,
            sources=list(self.evidence_sources),
        )


_EVIDENCE_NOISE_RE = re.compile(
    r"(?i)\b(?:awaiting\s+ocr|image\s+vision\s+abstain|urldefense|proofpoint|"
    r"mimecast|cgbannerindicator|&nbsp;|account\s+executive|"
    r"quotes\s+in\s+24|ai[\-\s]?driven\s+pmo|global\s+field\s+services|"
    r"powered\s+by\s+mimecast|mark\s+safe)\b"
)
_EVIDENCE_STOP = frozenset(
    {
        "the", "and", "for", "with", "from", "that", "this", "have", "will",
        "are", "was", "were", "been", "confirm", "which", "what", "who",
        "room", "must", "need", "needs", "please", "into", "onto", "over",
    }
)


def _evidence_tokens(text: str) -> set[str]:
    return {
        t
        for t in re.findall(r"[a-z0-9][a-z0-9\-\./]{2,}", (text or "").lower())
        if t not in _EVIDENCE_STOP and not t.isdigit()
    }


def _atom_evidence_text(atom: Mapping[str, Any]) -> str:
    text = re.sub(r"\s+", " ", (_atom_text(atom) or "").strip())
    # Vision extractors sometimes serialize a one-item JSON string list.
    if len(text) >= 4 and text[0] in "[{\"'":
        try:
            import json

            parsed = json.loads(text)
            if isinstance(parsed, list) and parsed:
                first = parsed[0]
                if isinstance(first, str) and first.strip():
                    text = first.strip()
            elif isinstance(parsed, str) and parsed.strip():
                text = parsed.strip()
        except Exception:
            pass
    # Vision sometimes emits mismatched wrappers: ["…'] or ['…"]
    if len(text) > 4 and text[0] == "[" and text[-1] == "]" and text[1] in "'\"" and text[-2] in "'\"":
        text = text[2:-2].replace('\\"', '"').replace("\\'", "'").strip()
    return re.sub(r"\s+", " ", text).strip()


def _atom_filename(atom: Mapping[str, Any], docs_by_id: Mapping[str, str] | None = None) -> str:
    loc = atom.get("locator") if isinstance(atom.get("locator"), Mapping) else {}
    for key in ("filename", "path", "source_path"):
        raw = loc.get(key) if isinstance(loc, Mapping) else None
        if not raw:
            raw = atom.get(key)
        if isinstance(raw, str) and raw.strip():
            name = raw.replace("\\", "/").rstrip("/").split("/")[-1]
            if name:
                return name
    aid = str(atom.get("artifact_id") or "").strip()
    if aid and docs_by_id and aid in docs_by_id:
        return docs_by_id[aid]
    if aid:
        return aid
    return "Source"


_FACT_KIND_LABEL = {
    "cable": "cables in frame",
    "mount": "mount / bracket",
    "equipment": "equipment in frame",
    "placement": "placement / position",
    "site_condition": "site condition",
    "annotation": "on-image annotation",
    "power_data": "power / network path",
    "risk": "install risk in frame",
    "other": "visible detail",
}
_VAGUE_ROOM_OVERVIEW_RE = re.compile(
    r"(?i)^(?:the\s+image\s+(?:shows|depicts)|this\s+(?:image|photo)\s+(?:shows|depicts)|"
    r"a\s+conference\s+room\s+setup\s+with\s+a\s+(?:long|large))",
)


def _atom_payload_maps(atom: Mapping[str, Any]) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    val = atom.get("value") if isinstance(atom.get("value"), Mapping) else {}
    st = atom.get("structured") if isinstance(atom.get("structured"), Mapping) else {}
    return val or {}, st or {}


def _parse_region_ref(region_ref: str) -> tuple[int | None, int | None]:
    m = re.match(r"(?i)page\s*(\d+)\s*/\s*image\s*(\d+)", (region_ref or "").strip())
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2))


def _atoms_by_id(atoms: Iterable[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    out: dict[str, Mapping[str, Any]] = {}
    for a in atoms:
        if not isinstance(a, Mapping):
            continue
        aid = str(a.get("id") or a.get("atom_id") or "").strip()
        if aid:
            out[aid] = a
    return out


def _photo_meta(
    atom: Mapping[str, Any],
    *,
    atoms_by_id: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Extract pointed photo location + caption for an atom."""
    loc = atom.get("locator") if isinstance(atom.get("locator"), Mapping) else {}
    val, st = _atom_payload_maps(atom)
    region = str(
        (loc or {}).get("region_ref")
        or val.get("region_ref")
        or st.get("region_ref")
        or ""
    ).strip()
    page = (loc or {}).get("page") or (loc or {}).get("page_number")
    image_n = (loc or {}).get("image") or (loc or {}).get("image_index")
    p2, i2 = _parse_region_ref(region)
    if page is None:
        page = p2
    if image_n is None:
        image_n = i2
    via = str(val.get("via") or st.get("via") or (loc or {}).get("extraction") or "")
    kind = str(val.get("image_kind") or st.get("image_kind") or st.get("kind") or "")
    fact_kind = str(val.get("fact_kind") or st.get("fact_kind") or "")
    if fact_kind.startswith("image_fact:"):
        fact_kind = fact_kind.split(":", 1)[1]
    is_photo = bool(
        region
        or "pdf_image_vision" in via
        or kind in {"photo", "image_marker", "diagram"}
        or fact_kind
    )
    caption = str(st.get("expected_content") or val.get("expected_content") or "").strip()
    marker_id = str(val.get("source_marker_id") or st.get("source_marker_id") or "").strip()
    if not caption and marker_id and atoms_by_id:
        marker = atoms_by_id.get(marker_id)
        if isinstance(marker, Mapping):
            mval, mst = _atom_payload_maps(marker)
            caption = str(
                mst.get("expected_content")
                or mval.get("expected_content")
                or ""
            ).strip()
            if not caption:
                mt = _atom_evidence_text(marker)
                m = re.search(r'(?i)expected:\s*"([^"]+)"', mt)
                if m:
                    caption = m.group(1).strip()
    # Caption sometimes lives in the fact text itself ("Image caption reads 'Behind TV 1'").
    if not caption:
        t = _atom_evidence_text(atom)
        m = re.search(
            r"(?i)(?:caption\s+reads|labeled\s+as|label(?:led)?)\s*[:\s]+['\"]([^'\"]+)['\"]",
            t,
        )
        if m:
            caption = m.group(1).strip()
    saved = str(
        (loc or {}).get("saved_path")
        or st.get("saved_path")
        or val.get("saved_path")
        or ""
    ).strip()
    if saved:
        saved = saved.replace("\\", "/").split("/")[-1]
    return {
        "is_photo": is_photo,
        "page": int(page) if page is not None and str(page).isdigit() else page,
        "image": int(image_n) if image_n is not None and str(image_n).isdigit() else image_n,
        "region_ref": region,
        "caption": caption,
        "fact_kind": fact_kind,
        "image_kind": kind or ("photo" if is_photo else ""),
        "saved_path": saved,
        "via": via,
    }


def _fact_kind_phrase(fact_kind: str) -> str:
    fk = (fact_kind or "").strip().lower()
    if not fk:
        return ""
    return _FACT_KIND_LABEL.get(fk, fk.replace("_", " "))


def _atom_locator_label(
    atom: Mapping[str, Any],
    snippet: str,
    *,
    atoms_by_id: Mapping[str, Mapping[str, Any]] | None = None,
) -> str:
    """Pointed where-string for the Evidence panel (page / image / caption)."""
    meta = _photo_meta(atom, atoms_by_id=atoms_by_id)
    parts: list[str] = []
    if meta["is_photo"]:
        parts.append("Photo")
        if meta["page"] is not None:
            parts.append(f"page {meta['page']}")
        if meta["image"] is not None:
            parts.append(f"image {meta['image']}")
        elif meta["region_ref"]:
            parts.append(meta["region_ref"])
        if meta["caption"]:
            parts.append(f"caption “{meta['caption'][:60]}”")
        kind_phrase = _fact_kind_phrase(str(meta["fact_kind"] or ""))
        if kind_phrase:
            parts.append(kind_phrase)
        if meta["saved_path"]:
            parts.append(meta["saved_path"])
    else:
        loc = atom.get("locator") if isinstance(atom.get("locator"), Mapping) else {}
        if isinstance(loc, Mapping):
            page = loc.get("page") or loc.get("page_number")
            section = loc.get("section") or loc.get("section_path")
            if page is not None:
                parts.append(f"page {page}")
            if section:
                if isinstance(section, (list, tuple)):
                    parts.append(" / ".join(str(x) for x in section[:3]))
                else:
                    parts.append(str(section)[:80])
        atype = str(atom.get("atom_type") or "").strip()
        if atype:
            parts.append(atype)
    label = " · ".join(parts) if parts else "evidence"
    return label[:180]


def _pointed_snippet(
    atom: Mapping[str, Any],
    text: str,
    *,
    atoms_by_id: Mapping[str, Mapping[str, Any]] | None = None,
) -> str:
    """What to show as the quote — lead with where/what for photos."""
    meta = _photo_meta(atom, atoms_by_id=atoms_by_id)
    body = text if len(text) <= 200 else text[:197].rstrip() + "…"
    if not meta["is_photo"]:
        return body
    where: list[str] = []
    if meta["page"] is not None and meta["image"] is not None:
        where.append(f"p{meta['page']}/image{meta['image']}")
    elif meta["region_ref"]:
        where.append(str(meta["region_ref"]))
    elif meta["page"] is not None:
        where.append(f"p{meta['page']}")
    if meta["caption"]:
        where.append(f"“{meta['caption'][:50]}”")
    kind_phrase = _fact_kind_phrase(str(meta["fact_kind"] or ""))
    head = "Photo " + " · ".join(where) if where else "Photo"
    if kind_phrase:
        return f"{head} — {kind_phrase}: {body}"
    return f"{head} — what we see: {body}"


def _pointed_observed(sources: list[dict[str, Any]]) -> str:
    bits: list[str] = []
    for s in sources[:2]:
        loc = str(s.get("locator") or "").strip()
        snip = str(s.get("snippet") or "").strip()
        if snip.lower().startswith("photo "):
            bits.append(snip[:180])
        elif loc and snip:
            bits.append(f"{loc}: {snip[:120]}")
        elif snip:
            bits.append(snip[:160])
    if not bits:
        return ""
    observed = "Evidence: " + " · ".join(bits)
    if len(sources) > 2:
        observed += f" · (+{len(sources) - 2} more)"
    return observed


def _docs_by_artifact_id(envelope: Mapping[str, Any] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    if not isinstance(envelope, Mapping):
        return out
    for doc in envelope.get("documents") or []:
        if not isinstance(doc, Mapping):
            continue
        aid = str(doc.get("artifact_id") or doc.get("id") or "").strip()
        name = str(doc.get("filename") or doc.get("name") or "").strip()
        if aid and name:
            out[aid] = name
    return out


def _score_atom_for_evidence(
    atom: Mapping[str, Any],
    *,
    trigger: re.Pattern[str] | None,
    question: str,
    prefer_photo: bool = True,
) -> float:
    """Return match score; 0 means reject (noise / no overlap)."""
    text = _atom_evidence_text(atom)
    if len(text) < 12 or _EVIDENCE_NOISE_RE.search(text):
        return 0.0
    # O10: whole-room blurbs never win as primary evidence.
    if _VAGUE_ROOM_OVERVIEW_RE.search(text) and len(text) > 120:
        # Allow only as last-resort if trigger hits annotation language.
        if not (
            trigger is not None
            and trigger.search(text)
            and re.search(r"(?i)behind\s+the\s+wall|annotation|hdmi|yealink|neat", text)
        ):
            return 0.0
    q_toks = _evidence_tokens(question)
    a_toks = _evidence_tokens(text)
    if not a_toks:
        return 0.0
    overlap = len(q_toks & a_toks) / max(len(q_toks), 1)
    trig_hit = bool(trigger.search(text)) if trigger is not None else False
    if not trig_hit and overlap < 0.12 and len(q_toks & a_toks) < 2:
        return 0.0
    score = 0.35 * float(trig_hit) + 0.55 * min(1.0, overlap * 2.2)
    # Prefer photo / install vision and concrete scope atoms.
    via_blob = json_dumps_safe(atom.get("value")) + json_dumps_safe(atom.get("structured"))
    if prefer_photo and ("pdf_image_vision" in via_blob or "image_" in via_blob):
        score += 0.12
    atype = str(atom.get("atom_type") or "").lower()
    if atype in {"scope_item", "open_question", "constraint", "risk", "decision"}:
        score += 0.06
    if atype in {"deal_metadata", "stakeholder"} and not trig_hit:
        score -= 0.15
    # O10 / P4: Prefer pointed install facts over vague whole-room captions.
    val, st = _atom_payload_maps(atom)
    fk = str(val.get("fact_kind") or st.get("fact_kind") or "")
    rank = str(val.get("evidence_rank") or st.get("evidence_rank") or "")
    if fk.startswith("image_fact") or "image_fact" in fk:
        score += 0.18
    if any(k in fk for k in ("cable", "annotation", "mount", "power_data", "equipment")):
        score += 0.10
    if "image_description" in fk or fk == "description" or rank == "blurb":
        score -= 0.28
    if _VAGUE_ROOM_OVERVIEW_RE.search(text) and len(text) > 160:
        score -= 0.35
    # Triple-check: if trigger exists, require trigger OR strong keyword overlap.
    if trigger is not None and not trig_hit and len(q_toks & a_toks) < 3:
        return 0.0
    return max(0.0, min(1.0, score))


def json_dumps_safe(obj: Any) -> str:
    try:
        import json

        return json.dumps(obj or {}, default=str).lower()
    except Exception:
        return str(obj or "").lower()


def _source_from_atom(
    atom: Mapping[str, Any],
    text: str,
    *,
    score: float,
    docs_by_id: Mapping[str, str] | None = None,
    atoms_by_id: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    meta = _photo_meta(atom, atoms_by_id=atoms_by_id)
    aid = str(atom.get("id") or atom.get("atom_id") or "").strip()
    src = {
        "filename": _atom_filename(atom, docs_by_id),
        "artifact_id": str(atom.get("artifact_id") or "") or None,
        "atom_id": aid or None,
        "locator": _atom_locator_label(atom, text, atoms_by_id=atoms_by_id),
        "snippet": _pointed_snippet(atom, text, atoms_by_id=atoms_by_id),
        "match_score": round(score, 3),
        "region_ref": meta.get("region_ref") or None,
        "page": meta.get("page"),
        "image": meta.get("image"),
        "caption": meta.get("caption") or None,
        "fact_kind": meta.get("fact_kind") or None,
        "media": "photo" if meta.get("is_photo") else "text",
    }
    return {k: v for k, v in src.items() if v not in (None, "")}


def _collect_matching_evidence(
    atoms: Iterable[Mapping[str, Any]],
    *,
    question: str,
    trigger: re.Pattern[str] | None = None,
    docs_by_id: Mapping[str, str] | None = None,
    atoms_by_id: Mapping[str, Mapping[str, Any]] | None = None,
    limit: int = 3,
    min_score: float = 0.42,
) -> tuple[list[dict[str, Any]], list[str], str]:
    """Pick best matching atoms; return (sources, atom_ids, observed_summary)."""
    atom_list = [a for a in atoms if isinstance(a, Mapping)]
    by_id = atoms_by_id or _atoms_by_id(atom_list)
    ranked: list[tuple[float, Mapping[str, Any], str]] = []
    for atom in atom_list:
        score = _score_atom_for_evidence(
            atom, trigger=trigger, question=question, prefer_photo=True
        )
        if score < min_score:
            continue
        text = _atom_evidence_text(atom)
        ranked.append((score, atom, text))
    ranked.sort(key=lambda row: (-row[0], -len(row[2])))
    sources: list[dict[str, Any]] = []
    ids: list[str] = []
    seen_snip: set[str] = set()
    seen_region: set[str] = set()
    for score, atom, text in ranked:
        # Final match gate: quote must still contain trigger or shared keywords.
        if trigger is not None and not trigger.search(text):
            shared = _evidence_tokens(question) & _evidence_tokens(text)
            if len(shared) < 2:
                continue
        snip_key = re.sub(r"\W+", " ", text.lower()).strip()[:120]
        if snip_key in seen_snip:
            continue
        meta = _photo_meta(atom, atoms_by_id=by_id)
        region_key = str(meta.get("region_ref") or "")
        # Keep at most two facts from the same photo crop so the panel stays pointed.
        if region_key:
            same = sum(1 for s in sources if s.get("region_ref") == region_key)
            if same >= 2:
                continue
            seen_region.add(region_key)
        seen_snip.add(snip_key)
        src = _source_from_atom(
            atom,
            text,
            score=score,
            docs_by_id=docs_by_id,
            atoms_by_id=by_id,
        )
        sources.append(src)
        aid = str(atom.get("id") or atom.get("atom_id") or "").strip()
        if aid:
            ids.append(aid)
        if len(sources) >= limit:
            break
    if not sources:
        return [], [], ""
    return sources, ids, _pointed_observed(sources)


def _repoint_sources(
    sources: list[dict[str, Any]],
    *,
    atoms: Iterable[Mapping[str, Any]],
    docs_by_id: Mapping[str, str] | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """Upgrade already-attached sources with pointed photo where/what labels."""
    by_id = _atoms_by_id(atoms)
    out: list[dict[str, Any]] = []
    for s in sources:
        if not isinstance(s, Mapping):
            continue
        aid = str(s.get("atom_id") or "").strip()
        atom = by_id.get(aid)
        if atom is None:
            out.append(dict(s))
            continue
        text = _atom_evidence_text(atom) or str(s.get("snippet") or "")
        score = float(s.get("match_score") or 0.9)
        out.append(
            _source_from_atom(
                atom,
                text,
                score=score,
                docs_by_id=docs_by_id,
                atoms_by_id=by_id,
            )
        )
    return out, _pointed_observed(out)


def _with_evidence(
    candidate: QuestionCandidate,
    *,
    atoms: Iterable[Mapping[str, Any]],
    trigger: re.Pattern[str] | None = None,
    docs_by_id: Mapping[str, str] | None = None,
    require: bool = False,
) -> QuestionCandidate | None:
    """Attach matching sources; drop candidate when require=True and nothing matches."""
    atom_list = [a for a in atoms if isinstance(a, Mapping)]
    if candidate.evidence_sources:
        sources, observed = _repoint_sources(
            list(candidate.evidence_sources),
            atoms=atom_list,
            docs_by_id=docs_by_id,
        )
        return QuestionCandidate(
            rule_id=candidate.rule_id,
            domain_id=candidate.domain_id,
            label=candidate.label,
            severity=candidate.severity,
            message=candidate.message,
            suggested_open_question=candidate.suggested_open_question,
            observed_summary=observed or candidate.observed_summary,
            source=candidate.source,
            score=candidate.score,
            evidence_atom_ids=list(candidate.evidence_atom_ids),
            evidence_sources=sources,
            project_mode=candidate.project_mode,
        )
    sources, ids, observed = _collect_matching_evidence(
        atom_list,
        question=candidate.suggested_open_question or candidate.message or candidate.label,
        trigger=trigger,
        docs_by_id=docs_by_id,
    )
    if not sources:
        if require:
            return None
        return candidate
    return QuestionCandidate(
        rule_id=candidate.rule_id,
        domain_id=candidate.domain_id,
        label=candidate.label,
        severity=candidate.severity,
        message=candidate.message,
        suggested_open_question=candidate.suggested_open_question,
        observed_summary=observed or candidate.observed_summary,
        source=candidate.source,
        score=min(1.0, candidate.score + 0.03),
        evidence_atom_ids=ids or list(candidate.evidence_atom_ids),
        evidence_sources=sources,
        project_mode=candidate.project_mode,
    )


def _blob_from_atoms(atoms: Iterable[Mapping[str, Any]]) -> str:
    return "\n".join(_atom_text(a) for a in atoms if isinstance(a, Mapping))


def _atoms_from_sources(
    envelope: Mapping[str, Any] | None,
    report: Mapping[str, Any] | None,
) -> list[Mapping[str, Any]]:
    out: list[Mapping[str, Any]] = []
    seen: set[str] = set()

    def add(atom: Any) -> None:
        if not isinstance(atom, Mapping):
            return
        aid = str(atom.get("id") or atom.get("atom_id") or id(atom))
        if aid in seen:
            return
        seen.add(aid)
        out.append(atom)

    if isinstance(envelope, Mapping):
        for a in envelope.get("atoms") or []:
            add(a)
    if isinstance(report, Mapping):
        for a in report.get("atoms") or []:
            add(a)
        for art in report.get("artifacts") or []:
            if isinstance(art, Mapping):
                for a in art.get("atoms") or []:
                    add(a)
    return out


def detect_project_mode(
    *,
    atoms: Iterable[Mapping[str, Any]] = (),
    service_routing: Mapping[str, Any] | None = None,
    pack_prior: Mapping[str, Any] | None = None,
    blob: str | None = None,
) -> str:
    """Universal project-mode detector — not Sodexo-specific."""
    text = blob if blob is not None else _blob_from_atoms(atoms)
    sr = service_routing or {}
    # O9: when the neural router abstains (or lacks anchors), ignore its
    # primary / neural_primary — evidence + pack prior decide mode.
    if sr.get("abstained") or str(sr.get("abstain_reason") or "").strip():
        primary = ""
    else:
        primary = str(sr.get("primary") or "").strip()
        # Never promote neural_primary when primary is empty/null.
        if not primary:
            primary = ""
    override_reason = str(sr.get("override_reason") or "").lower()
    source = str(sr.get("source") or "").lower()

    if (
        "network_install" in override_reason
        or "network_install" in source
        or _NETWORK_INSTALL_EVIDENCE_RE.search(text or "")
    ):
        return MODE_NETWORK_EDGE_INSTALL

    if primary == "network_maintenance":
        # Install evidence wins over ops pack id.
        if _NETWORK_INSTALL_EVIDENCE_RE.search(text or ""):
            return MODE_NETWORK_EDGE_INSTALL
        return MODE_NETWORK_OPS

    text_s = text or ""
    av_strong_n = len(_AV_STRONG_RE.findall(text_s))
    wireless_strong = bool(_WIRELESS_STRONG_RE.search(text_s))
    wireless_weak = bool(_WIRELESS_WEAK_RE.search(text_s))

    # Conference-room / UC-AV evidence wins over a single marketing "WiFi".
    if primary == "audio_visual" or av_strong_n >= 2 or (
        _AV_RE.search(text_s) and av_strong_n >= 1 and not wireless_strong
    ):
        return MODE_AV

    if primary == "wireless" or wireless_strong or (
        wireless_weak and av_strong_n == 0 and not _AV_RE.search(text_s)
    ):
        if _CONFIG_ONLY_RE.search(text_s):
            return MODE_WIRELESS_CONFIG
        return MODE_WIRELESS_INSTALL

    if primary in {"low_voltage_cabling", "cabling"} or _CABLING_RE.search(text_s):
        return MODE_CABLING

    if primary == "alm" or _ALM_RE.search(text_s):
        return MODE_ALM

    # Staff-aug only when router primary is trusted (not abstained) OR
    # strong staff-aug evidence without AV/wireless install signals.
    if primary == "staff_augmentation" or (
        _STAFF_AUG_RE.search(text_s) and av_strong_n == 0 and not wireless_strong
    ):
        # Remote-hands on network install already returned above.
        return MODE_STAFF_AUG

    if _AV_RE.search(text_s):
        return MODE_AV

    if primary == "access_control" or _ACCESS_RE.search(text_s):
        return MODE_ACCESS

    top = str((pack_prior or {}).get("top_pack_id") or "")
    if top and top in {
        "network_maintenance",
        "wireless",
        "alm",
        "staff_augmentation",
        "audio_visual",
        "access_control",
        "low_voltage_cabling",
    }:
        return detect_project_mode(
            atoms=(),
            service_routing={"primary": top, "enabled": True, "confidence": 0.5},
            blob=text,
        )
    return MODE_GENERIC


def _atom_question_text(atom: Mapping[str, Any]) -> str:
    for key in ("raw_text", "text", "normalized_text", "claim", "normalized_claim"):
        val = atom.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    value = atom.get("value")
    if isinstance(value, Mapping):
        for key in ("question", "text", "claim", "summary"):
            val = value.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    if isinstance(value, str) and value.strip():
        return value.strip()
    return ""


_SMALLTALK_RE = re.compile(
    r"(?i)\b("
    r"weekend|volleyball|how(?:'s| is| are)?\s+you(?:r)?(?:\s+doing)?|"
    r"big\s+plans|you\s+know\s+what\s+i\s+mean|chase\b|"
    r"how's\s+it\s+going|what'?s\s+up|good\s+morning|good\s+afternoon|"
    r"catch\s+up|how's\s+the\s+family|nice\s+to\s+(?:meet|see)\s+you|"
    r"point\s+of\s+emphasis\b|rhyme\s+or\s+reason|"
    r"scenarios\s+with\s+the\s+international"
    r")\b"
)


def _is_customer_facing_question(text: str) -> bool:
    """Filter parser-internal / meta chatter that is not a PM ask."""
    t = (text or "").strip()
    if len(t) < 12:
        return False
    low = t.lower()
    # Internal chatter / copy-of-sites when we already have site clusters
    banned = (
        "verify each published site",
        "kind=physical_site",
        "atom_type",
        "copy of those sites that you can send",
        "do you have a copy of those sites",
        "rhyme or reason",
        "in those scenarios with the international",
        "big plans for the weekend",
        "why do you chase",
        "you know what i mean",
        "biggest point of emphasis",
    )
    if any(b in low for b in banned):
        return False
    if _SMALLTALK_RE.search(low):
        return False
    # Email footer / security-gateway chrome is not a PM clarification.
    if any(
        tok in low
        for tok in (
            "urldefense.proofpoint.com",
            "mimecastcybergraph.com",
            "mimecast.com",
            "report.mimecast",
            "mark safe<",
            "purtera-it.com<http",
        )
    ):
        return False
    # Mostly-a-URL "questions"
    if low.count("http") >= 1 and sum(ch.isalnum() for ch in t) < 40:
        return False
    # Prefer interrogatives or decision-shaped statements
    if "?" in t:
        return True
    decision_starts = (
        "confirm ",
        "decide ",
        "clarify ",
        "which ",
        "who ",
        "what ",
        "when ",
        "where ",
        "how ",
        "is it ",
        "are we ",
        "once we know",
        "need to know",
    )
    return any(low.startswith(s) or f" {s}" in f" {low}" for s in decision_starts)


# Soft vision observations that must not become install blockers.
# Floor trip-hazard is already covered by mode.av_install.floor_network_path.
_SPECULATIVE_ROOM_RISK_RE = re.compile(
    r"(?i)(?:"
    r"(?:may|could|might)\s+pose|may\s+impact|potentially\s+affecting|slight\s+trip|"
    r"patterned\s+carpet|non[\-\s]?standard\s+tile|field\s+of\s+view|"
    r"pose\s+a\s+(?:potential\s+|minor\s+)?(?:obstruction|trip\s+hazard)|"
    r"pose\s+a\s+[^.]{0,40}?trip\s+hazard|"
    r"\bbackpack\b|personal\s+(?:belongings|items|effects)|minor\s+obstruction"
    r")",
)
def _candidates_from_evidence_atoms(
    atoms: Iterable[Mapping[str, Any]],
    *,
    project_mode: str,
    evidence_blob: str = "",
    docs_by_id: Mapping[str, str] | None = None,
) -> list[QuestionCandidate]:
    atom_list = [a for a in atoms if isinstance(a, Mapping)]
    by_id = _atoms_by_id(atom_list)
    out: list[QuestionCandidate] = []
    seen_fp: set[str] = set()
    for atom in atom_list:
        atype = str(atom.get("atom_type") or "").lower()
        # Never promote chat/meta atoms — greetings land here after parser noise filters.
        if atype in {
            "deal_metadata",
            "conversation_meta",
            "tag",
            "note_meta",
            "entity",
            "person",
        }:
            continue
        if atype not in {
            "open_question",
            "decision",
            "risk",
            "action_item",
            "missing_info",
            "gap",
        }:
            # Also accept scope_item / constraint that are clearly questions
            text_probe = _atom_question_text(atom)
            if "?" not in text_probe and not text_probe.lower().startswith("once we know"):
                continue
        text = _atom_question_text(atom)
        if not _is_customer_facing_question(text):
            continue
        # Soft-filter ops language on install mode
        if project_mode == MODE_NETWORK_EDGE_INSTALL:
            if re.search(
                r"\b("
                r"gold[\-\s]?image|firmware\s+baseline|vlan\s+audit|oem\s+tac|smartnet|"
                r"routing\s+protocol|failover\s+test|bgp|ospf|eigrp|"
                r"patch\s+window|change\s+calendar|coverage\s+tier"
                r")\b",
                text,
                re.I,
            ):
                continue
        # AV: drop speculative photo-room vibes / clutter — not scope asks.
        # Soft "could pose" / backpack / FOV risks must never become blockers.
        if (
            project_mode == MODE_AV
            and atype == "risk"
            and _SPECULATIVE_ROOM_RISK_RE.search(text)
        ):
            continue
        fp = fingerprint_question(text)
        if fp in seen_fp:
            continue
        seen_fp.add(fp)
        aid = str(atom.get("id") or atom.get("atom_id") or "")
        pm_q = _to_pm_question(text, evidence_blob=evidence_blob or text)
        if not (pm_q or "").strip():
            continue
        severity = "blocker" if atype in {"risk", "missing_info"} else "warning"
        # Prefer open_question / decision; demote still-casual rewrites slightly
        score = 0.92 if atype == "open_question" else 0.85 if atype == "decision" else 0.72
        if atype == "action_item" and "sop" in pm_q.lower():
            score = 0.94
        if "sop" in pm_q.lower() and atype == "open_question":
            score = 0.96
        if pm_q != text and atype == "open_question":
            score = max(score, 0.9)
        # Remaining soft "may/potentially" risks stay warnings, never blockers.
        if atype == "risk" and _SPECULATIVE_ROOM_RISK_RE.search(text):
            severity = "warning"
            score = min(score, 0.58)
        label = {
            "open_question": "Open project question",
            "decision": "Decision still open",
            "risk": "Risk needs owner answer",
            "action_item": "Action needs clarification",
        }.get(atype, "Project clarification")
        primary_source = _source_from_atom(
            atom,
            text,
            score=1.0,
            docs_by_id=docs_by_id,
            atoms_by_id=by_id,
        )
        out.append(
            QuestionCandidate(
                rule_id=f"evidence.{atype}.{fp[:48] or aid or 'q'}",
                domain_id="project",
                label=label,
                severity=severity,
                message=text,
                suggested_open_question=pm_q,
                observed_summary=_pointed_observed([primary_source]),
                source="evidence",
                score=score,
                evidence_atom_ids=[aid] if aid else [],
                evidence_sources=[primary_source],
                project_mode=project_mode,
            )
        )
    return out


def _to_pm_question(text: str, *, evidence_blob: str = "") -> str:
    """Normalize atom prose into a PM-facing question grounded in deal context."""
    t = re.sub(r"\s+", " ", (text or "").strip())
    if not t:
        return t
    low = t.lower()
    blob_low = (evidence_blob or "").lower()
    # Lift casual transcript into PM voice
    if "one device per site" in low or (
        low.startswith("once we know") and "device" in low
    ):
        return "Confirm topology: one edge device per site, or a shared/hub model?"
    if "copy of those sites" in low:
        return ""  # suppressed as non-PM
    if "white adapter" in low and "neat" in low:
        return (
            "Confirm whether a white adapter/mount is approved to suspend Neat devices "
            "at the front and back center of the room (per photo annotation)."
        )
    if (
        "copy of their sop" in low
        or ("sop" in low and ("copy" in low or "send" in low or "once available" in low))
    ):
        return (
            "Can we get the customer's SOP before the first site, "
            "and who owns revisions during the POC?"
        )
    if "who do you get approval from" in low or low.startswith("who do you get approval"):
        # Canada / CDW paper is owned by mode.phase_site_exclusions — avoid a
        # near-duplicate curated ask when that template will fire.
        if re.search(r"\b(?:montreal|canada|cdw|us\s+paper|paper)\b", blob_low) or re.search(
            r"\b(?:montreal|canada|cdw|us\s+paper|paper)\b", low
        ):
            return ""
        # Bare approval with no commercial/paper context → drop (too generic).
        return ""
    if _SMALLTALK_RE.search(low):
        return ""
    if "by chance" in low or low.startswith("quinton,"):
        # Too conversational / person-directed — drop unless rewritten above
        if "sop" not in low:
            return ""
    if t.endswith("?") and len(t) < 220:
        return t[0].upper() + t[1:] if t[0].islower() else t
    if not t.endswith("?"):
        t = t.rstrip(".") + "?"
    return t[0].upper() + t[1:] if t and t[0].islower() else t


@dataclass(frozen=True)
class _ModeTemplate:
    rule_id: str
    domain_id: str
    label: str
    question: str
    message: str
    trigger: re.Pattern[str]
    # If this regex matches, the question is already answered → suppress
    answered_by: re.Pattern[str] | None = None
    severity: str = "warning"
    score: float = 0.8


_NETWORK_EDGE_TEMPLATES: tuple[_ModeTemplate, ...] = (
    _ModeTemplate(
        rule_id="mode.network_edge_install.topology_per_site",
        domain_id="network_edge_install",
        label="Edge topology per site",
        question="Confirm topology: one Meraki MX (or edge device) per site, or a shared/hub-and-spoke model?",
        message="Transcript left device-per-site topology open; BOM implies quantity but not topology.",
        trigger=re.compile(
            r"(?:one\s+device\s+per\s+site|meraki\s+mx|sd[\s\-]?wan|per\s+location|per\s+site)",
            re.I,
        ),
        answered_by=re.compile(
            r"\b(?:confirmed\s+one\s+(?:mx|device|appliance)\s+per\s+site|"
            r"one\s+(?:mx|device|appliance)\s+per\s+site\s+(?:confirmed|approved|agreed)|"
            r"hub[\-\s]?and[\-\s]?spoke\s+(?:confirmed|approved)|"
            r"shared\s+mx\s+for\s+all\s+sites)\b",
            re.I,
        ),
        severity="blocker",
        score=0.95,
    ),
    _ModeTemplate(
        rule_id="mode.network_edge_install.phase_site_exclusions",
        domain_id="network_edge_install",
        label="Phase / site exclusions",
        question=(
            "Which sites are in this phase vs deferred, who confirms the final "
            "in-scope set, and who approves any Canada work on CDW US paper "
            "versus deferring that site?"
        ),
        message="Skip/defer + Canada/US-paper language exists; phase boundary and paper path need a hard yes/no.",
        trigger=re.compile(
            r"(?:will\s+(?:probaly|probably)?\s*not\s+do|montreal|keep\s+(?:everything\s+)?on\s+us\s+paper|"
            r"avoid\s+cdw\s+ca|etobicoke\s+has\s+already\s+been\s+done|cdw\s+us\s+paper)",
            re.I,
        ),
        score=0.92,
    ),
    _ModeTemplate(
        rule_id="mode.network_edge_install.first_survey_site",
        domain_id="network_edge_install",
        label="First survey / walkthrough site",
        question=(
            "Confirm the first site survey / POC walkthrough location "
            "(name the site), or the alternate if circuits are not ready, "
            "and who schedules customer access?"
        ),
        message="Site survey is planned but the first site is not locked.",
        trigger=re.compile(
            r"(?:site\s+survey|walkthrough|first\s+site\s+survey|which\s+one\s+of\s+these\s+sites|"
            r"leaning\s+to\s+be\s+in|likely\s+location)",
            re.I,
        ),
        answered_by=re.compile(
            r"\b(?:survey\s+site\s*(?:is|=)|walkthrough\s+at\s+[A-Z]|first\s+site:\s*"
            r"|confirmed\s+(?:maitland|survey\s+site))\b",
            re.I,
        ),
        score=0.88,
    ),
    _ModeTemplate(
        rule_id="mode.network_edge_install.survey_commercial",
        domain_id="commercial",
        label="Survey / commercial model",
        question="Is the site survey a separate charge (per-site fee / NTE), or included in the install quote?",
        message="Survey-charge language appeared without a locked commercial model.",
        trigger=re.compile(r"(?:site\s+survey\s+charge|survey\s+charge|charge\s+for)", re.I),
        answered_by=re.compile(
            r"\b(?:fixed\s+fee|t\s*&\s*m|time\s+and\s+materials|nte|not\s+to\s+exceed|"
            r"per[\-\s]?site\s+(?:rate|fee|price)\s+of\s+\$)\b",
            re.I,
        ),
        score=0.86,
    ),
    _ModeTemplate(
        rule_id="mode.network_edge_install.acceptance_signer",
        domain_id="network_edge_install",
        label="POC / SOP acceptance owner",
        question="Who signs POC / SOP acceptance after the first site, and what is the pass/fail criteria?",
        message="POC/SOP is mentioned; acceptance owner and criteria are fuzzy.",
        trigger=re.compile(r"\b(?:poc|sop)\b", re.I),
        answered_by=re.compile(
            r"\b(?:signed\s+by|acceptance\s+owner|customer\s+sign[\-\s]?off\s+is)\b",
            re.I,
        ),
        score=0.84,
    ),
    _ModeTemplate(
        rule_id="mode.network_edge_install.circuit_ready",
        domain_id="network_edge_install",
        label="Circuit readiness for first site",
        question=(
            "Confirm circuit readiness at the first survey / POC site — "
            "is that site carrier-ready, or should we schedule an alternate?"
        ),
        message="Circuit spin-up is a schedule dependency for the first smart-hands visit.",
        trigger=re.compile(
            r"(?:turning\s+on\s+the\s+circuits|circuits?\s+spun\s+up|circuit(?:s)?\s+at\s+(?:each|these)|"
            r"longer\s+for\s+them\s+to\s+get\s+the\s+circuits)",
            re.I,
        ),
        score=0.83,
    ),
    _ModeTemplate(
        rule_id="mode.network_edge_install.smart_hands_scope",
        domain_id="network_edge_install",
        label="Smart-hands scope boundary",
        question="Is onsite scope limited to physical install of the SD-WAN gear, or does it include configuration, testing, and documentation?",
        message="Smart/remote hands mentioned; scope past physical rack-and-stack is unclear.",
        trigger=re.compile(r"\b(?:smart\s+hands|remote\s+hands|physical\s+install)\b", re.I),
        answered_by=re.compile(
            r"\b(?:config(?:uration)?\s+included|rack[\-\s]?and[\-\s]?stack\s+only|"
            r"physical\s+install\s+only)\b",
            re.I,
        ),
        score=0.82,
    ),
)

_MODE_TEMPLATES: dict[str, tuple[_ModeTemplate, ...]] = {
    MODE_NETWORK_EDGE_INSTALL: _NETWORK_EDGE_TEMPLATES,
    MODE_NETWORK_OPS: (
        _ModeTemplate(
            rule_id="mode.network_ops.coverage_tier",
            domain_id="network_maintenance",
            label="Support coverage tier",
            question="What support coverage tier and renewal status apply to each device family?",
            message="Ongoing network ops needs an explicit coverage tier.",
            trigger=re.compile(r"\b(?:smartnet|support\s+contract|maintenance|ops)\b", re.I),
            score=0.8,
        ),
        _ModeTemplate(
            rule_id="mode.network_ops.change_window",
            domain_id="network_maintenance",
            label="Change / patch window",
            question="What recurring patch/change window and rollback process apply?",
            message="Ops engagement needs a published change window.",
            trigger=re.compile(r"\b(?:patch|firmware|change\s+window|maintenance\s+window)\b", re.I),
            score=0.78,
        ),
    ),
    MODE_WIRELESS_INSTALL: (
        _ModeTemplate(
            rule_id="mode.wireless_install.ap_count_model",
            domain_id="wireless",
            label="AP count / model",
            question="How many APs and what AP model(s) are in scope?",
            message="Wireless install without a locked AP count/model.",
            trigger=re.compile(
                r"\b(?:access\s+points?|wlan\s+install|wireless\s+install|ssid|heatmap)\b",
                re.I,
            ),
            answered_by=re.compile(r"\b\d+\s*(?:x\s*)?(?:aps?|access\s+points?)\b", re.I),
            severity="blocker",
            score=0.93,
        ),
    ),
    MODE_AV: (
        _ModeTemplate(
            rule_id="mode.av_install.cable_conceal_drywall",
            domain_id="audio_visual",
            label="In-wall cable concealment / drywall finish",
            question=(
                "Photos show surface cable runs and notes to move cables behind the wall — "
                "confirm in-wall fish vs surface raceway, and who owns drywall cut / patch / paint?"
            ),
            message=(
                "Aesthetic / behind-the-wall cable path is implied but drywall ownership "
                "and pathway method are not locked."
            ),
            trigger=re.compile(
                r"\b(?:behind\s+the\s+wall|in[\-\s]?wall|conceal|cable\s+management|"
                r"reroute|visible\s+cables?|loose\s+cables?|raceway|drywall|patch(?:ing)?\s*/?\s*paint)\b",
                re.I,
            ),
            answered_by=re.compile(
                r"\b(?:customer\s+owns\s+(?:drywall|patch|paint)|"
                r"surface\s+raceway\s+only|in[\-\s]?wall\s+(?:approved|confirmed)|"
                r"no\s+drywall|gc\s+owns\s+patch)\b",
                re.I,
            ),
            severity="blocker",
            score=0.96,
        ),
        _ModeTemplate(
            rule_id="mode.av_install.keep_vs_remove_displays",
            domain_id="audio_visual",
            label="Existing displays keep vs remove",
            question=(
                "Confirm annotated keep vs remove: which existing TVs/displays stay in place, "
                "and which codecs / bars are removed vs reused? "
                "(Include whether HDMI over Ethernet / HDMI Replicator keepers remain.)"
            ),
            message="Photo annotations call out keep/remove for existing AV gear — not locked in SOW.",
            trigger=re.compile(
                r"\b(?:stay\s+in\s+place|tvs?\s+to\s+stay|remain\s+in\s+(?:their\s+)?(?:current\s+)?position|"
                r"will\s+be\s+removed|except\s+for|hdmi\s+replicator|hdmi\s+over\s+ethernet)\b",
                re.I,
            ),
            answered_by=re.compile(
                r"\b(?:confirmed\s+keep|reuse\s+existing\s+displays?|remove\s+all\s+existing)\b",
                re.I,
            ),
            severity="blocker",
            score=0.94,
        ),
        _ModeTemplate(
            rule_id="mode.av_install.floor_network_path",
            domain_id="audio_visual",
            label="Floor network pathway method",
            question=(
                "Confirm the floor network path method: poke-through / floor box "
                "vs surface raceway for the ~10ft run to the receptacle."
            ),
            message="Vision notes network across the floor to a receptacle — pathway method unset.",
            trigger=re.compile(
                r"\b(?:across\s+the\s+floor|floor\s+network|floor\s+(?:box|receptacle)|"
                r"10\s+(?:ft|feet)|trip\s+hazard)\b",
                re.I,
            ),
            answered_by=re.compile(
                r"\b(?:floor\s+box\s+confirmed|poke[\-\s]?through\s+approved|surface\s+raceway\s+approved)\b",
                re.I,
            ),
            severity="warning",
            score=0.9,
        ),
        _ModeTemplate(
            rule_id="mode.av_install.replication_cable_path",
            domain_id="audio_visual",
            label="TV replication cable path",
            question=(
                "Confirm replication cable TV1→TV2 must be rerouted/hidden behind the wall "
                "per photo annotations, and who provides pathway?"
            ),
            message="Replication cable visibility / reroute is annotated on site photos.",
            trigger=re.compile(
                r"\b(?:replication\s+cable|reroute|tv\s*1|tv\s*2)\b",
                re.I,
            ),
            answered_by=re.compile(
                r"\b(?:replication\s+path\s+confirmed|new\s+in[\-\s]?wall\s+hdmi|hdbase\s*t\s+run\s+approved)\b",
                re.I,
            ),
            severity="blocker",
            score=0.93,
        ),
        _ModeTemplate(
            rule_id="mode.av_install.ceiling_tile_match",
            domain_id="audio_visual",
            label="Ceiling tile match after device removals",
            question=(
                "Photo notes say ceiling tiles are hard to get — after ceiling-device decommission, "
                "who supplies matching tiles / patch, and is tile match required?"
            ),
            message="Ceiling device removals + hard-to-match tiles are annotated.",
            trigger=re.compile(
                r"\b(?:ceiling\s+tiles?\s+as\s+they\s+are\s+hard\s+to\s+get|"
                r"hard\s+to\s+get.{0,40}ceiling\s+tiles?|"
                r"existing\s+ceiling\s+devices?\s*[-–—]?\s*decom)\b",
                re.I,
            ),
            answered_by=re.compile(
                r"\b(?:customer\s+owns\s+tiles?|tile\s+match\s+not\s+required|"
                r"gc\s+owns\s+ceiling\s+repair)\b",
                re.I,
            ),
            severity="warning",
            score=0.88,
        ),
    ),
    MODE_ALM: (
        _ModeTemplate(
            rule_id="mode.alm.environments",
            domain_id="alm",
            label="ALM environments",
            question="Which environments (dev/test/stage/prod) are in scope and what are the promotion gates?",
            message="ALM scope needs environment + gate clarity.",
            trigger=re.compile(r"\b(?:alm|release|environment|promotion)\b", re.I),
            score=0.85,
        ),
    ),
    MODE_STAFF_AUG: (
        _ModeTemplate(
            rule_id="mode.staff_aug.roles_clearance",
            domain_id="staff_augmentation",
            label="Roles / clearance",
            question="What roles, headcount, clearance level, and onsite vs remote mix are required?",
            message="Staff aug needs role/clearance definition.",
            trigger=re.compile(r"\b(?:staff\s+aug|resource|cleared|badged)\b", re.I),
            score=0.85,
        ),
    ),
}


def _ground_template_question(tmpl: _ModeTemplate, blob: str) -> str:
    """Specialize template wording with evidence anchors (city / lean site)."""
    q = tmpl.question
    if tmpl.rule_id != "mode.network_edge_install.first_survey_site":
        return q
    m = re.search(
        r"(?i)(?:leaning\s+to\s+be\s+in|likely\s+location[,\s]+(?:the\s+one\s+out\s+here\s+in\s+)?)"
        r"([A-Za-z][A-Za-z\s]+?)(?:,|\.|$|\s+but)",
        blob or "",
    )
    if not m:
        m = re.search(r"(?i)\b(Maitland)\b", blob or "")
    if not m:
        return q
    site = re.sub(r"\s+", " ", m.group(1)).strip(" .,")
    if len(site) < 3 or len(site) > 40:
        return q
    return (
        f"Confirm {site} as the first site survey / POC walkthrough, "
        "or name the alternate if circuits are not ready, and who schedules customer access?"
    )


def _candidates_from_mode_templates(
    *,
    project_mode: str,
    blob: str,
    atoms: Iterable[Mapping[str, Any]] = (),
    docs_by_id: Mapping[str, str] | None = None,
) -> list[QuestionCandidate]:
    atom_list = [a for a in atoms if isinstance(a, Mapping)]
    out: list[QuestionCandidate] = []
    for tmpl in _MODE_TEMPLATES.get(project_mode, ()):
        if not tmpl.trigger.search(blob or ""):
            continue
        if tmpl.answered_by is not None and tmpl.answered_by.search(blob or ""):
            continue
        question = _ground_template_question(tmpl, blob or "")
        cand = QuestionCandidate(
            rule_id=tmpl.rule_id,
            domain_id=tmpl.domain_id,
            label=tmpl.label,
            severity=tmpl.severity,
            message=tmpl.message,
            suggested_open_question=question,
            observed_summary=f"Mode template for {project_mode}",
            source="mode_template",
            score=tmpl.score + (0.04 if question != tmpl.question else 0.0),
            project_mode=project_mode,
        )
        # Mode asks must cite real atoms (usually photo annotations). No match → drop.
        grounded = _with_evidence(
            cand,
            atoms=atom_list,
            trigger=tmpl.trigger,
            docs_by_id=docs_by_id,
            require=True,
        )
        if grounded is None:
            continue
        out.append(grounded)
    return out


def _sites_answer_site_list_question(sites: list[SiteSummary], text: str) -> bool:
    """Suppress only 'send us the site list' chatter — not phase/circuit asks."""
    low = (text or "").lower()
    # Do NOT match "which sites are in this phase" / "which sites have circuits".
    # Narrow chatter only — avoid matching "final in-scope set" / phase asks.
    list_chatter = (
        "copy of those sites",
        "list of sites",
        "send over the sites",
        "send us the sites",
        "do you have a copy of those sites",
        "which physical site(s), buildings",
    )
    if not any(tok in low for tok in list_chatter):
        return False
    pub = sum(1 for s in sites if s.publishable)
    return pub >= 3


def _bom_answers_inventory(blob: str, text: str) -> bool:
    """If BOM already lists Meraki MX × N, don't ask for device inventory."""
    low = (text or "").lower()
    if not any(tok in low for tok in ("inventory", "how many", "what model", "device family")):
        return False
    return bool(re.search(r"\bmeraki\s+mx\b.*\b\d+\b|\b\d+\s*[×x]\s*meraki|\bmeraki\s+mx\s*[×x]\s*\d+", blob, re.I))


def suppress_answered(
    candidates: list[QuestionCandidate],
    *,
    blob: str,
    sites: list[SiteSummary],
) -> list[QuestionCandidate]:
    out: list[QuestionCandidate] = []
    for c in candidates:
        q = c.suggested_open_question or c.message
        if _sites_answer_site_list_question(sites, q):
            continue
        if _bom_answers_inventory(blob, q):
            continue
        # Empty after normalization
        if not (c.suggested_open_question or "").strip():
            continue
        out.append(c)
    return out


def apply_feedback(
    candidates: list[QuestionCandidate],
    policy: FeedbackPolicy,
    *,
    project_mode: str,
) -> list[QuestionCandidate]:
    suppressed_texts = list(policy.suppressed_texts or ())
    out: list[QuestionCandidate] = []
    for c in candidates:
        fp = fingerprint_question(c.suggested_open_question or c.message)
        if c.rule_id in policy.suppressed_rule_ids:
            continue
        if fp and fp in policy.suppressed_fingerprints:
            continue
        if (project_mode, c.rule_id) in policy.suppressed_mode_rules:
            continue
        qtext = c.suggested_open_question or c.message
        # Semantic neighbor of a dismissed ask (e.g. evidence paraphrase of
        # a dismissed mode-template topology question).
        if suppressed_texts and is_near_duplicate_of_any(qtext, suppressed_texts):
            continue
        # Apply preferred wording
        edit = policy.edits_by_rule.get(c.rule_id)
        if edit:
            c = QuestionCandidate(
                rule_id=c.rule_id,
                domain_id=c.domain_id,
                label=c.label,
                severity=c.severity,
                message=c.message,
                suggested_open_question=edit,
                observed_summary=c.observed_summary + " (PM-edited wording)",
                source=c.source,
                score=min(1.0, c.score + 0.05),
                evidence_atom_ids=list(c.evidence_atom_ids),
                evidence_sources=list(c.evidence_sources),
                project_mode=c.project_mode,
            )
        out.append(c)

    # Promote gold adds for this mode (+ global "")
    existing_fp = {
        fingerprint_question(c.suggested_open_question or c.message) for c in out
    }
    for mode_key in (project_mode, ""):
        for ev in policy.gold_by_mode.get(mode_key, ()):
            text = (ev.edited_text or ev.question_text or "").strip()
            if not text:
                continue
            fp = fingerprint_question(text)
            if fp in existing_fp:
                continue
            existing_fp.add(fp)
            out.append(
                QuestionCandidate(
                    rule_id=ev.rule_id or f"pm_gold.{fp[:48]}",
                    domain_id=ev.domain_id or "project",
                    label="PM-authored question",
                    severity="warning",
                    message="Promoted from prior PM feedback (gold add).",
                    suggested_open_question=text,
                    observed_summary=f"Gold add from deal {ev.deal_id or 'prior'}",
                    source="pm_gold",
                    score=0.97,
                    project_mode=project_mode,
                )
            )
    return out


def _yaml_safety_net(
    gaps: Iterable[GapCard],
    *,
    project_mode: str,
    existing_rule_ids: set[str],
    max_add: int = 2,
) -> list[QuestionCandidate]:
    """Rare holes only — mode-compatible blockers (then warnings) not already covered."""
    allow = _MODE_YAML_ALLOW.get(project_mode, _MODE_YAML_ALLOW[MODE_GENERIC])
    blockers: list[GapCard] = []
    warnings: list[GapCard] = []
    for g in gaps:
        if g.rule_id in existing_rule_ids:
            continue
        if g.domain_id not in allow and g.domain_id != "global":
            continue
        if any(g.rule_id.startswith(p) for p in _INSTALL_BANNED_RULE_PREFIXES):
            if project_mode == MODE_NETWORK_EDGE_INSTALL:
                continue
        if g.severity == "blocker":
            blockers.append(g)
        elif g.severity == "warning":
            warnings.append(g)
    picked = (blockers + warnings)[:max_add]
    out: list[QuestionCandidate] = []
    for g in picked:
        out.append(
            QuestionCandidate(
                rule_id=g.rule_id,
                domain_id=g.domain_id,
                label=g.label,
                severity=g.severity,
                message=g.message,
                suggested_open_question=g.suggested_open_question or g.message,
                observed_summary=g.observed_summary or "YAML safety-net",
                source="yaml_safety",
                score=0.55 if g.severity == "warning" else 0.7,
                project_mode=project_mode,
            )
        )
    return out


def _candidate_rank_tuple(c: QuestionCandidate) -> tuple:
    """Higher is better — used to pick the canonical ask in a cluster."""
    source_rank = {"pm_gold": 4, "evidence": 3, "mode_template": 2, "yaml_safety": 1}.get(
        c.source, 0
    )
    evidence_rank = 1 if c.evidence_sources else 0
    # PM-gold teaching rows must win their semantic cluster even without
    # citations yet (hash embedders falsely merge demarc vs survey asks).
    gold_boost = 1 if c.source == "pm_gold" else 0
    return (
        gold_boost,
        -SEVERITY_SORT.get(c.severity, 9),
        source_rank,
        evidence_rank,
        c.score,
        # Prefer slightly longer, more specific wording as canonical.
        min(len(c.suggested_open_question or c.message or ""), 240) / 240.0,
    )


def _apply_neural_evidence_scores(
    candidates: list[QuestionCandidate],
    *,
    evidence_blob: str,
) -> tuple[list[QuestionCandidate], dict[str, Any]]:
    """Re-score / filter candidates by neural relevance to deal evidence."""
    if not candidates:
        return candidates, {"neural_relevance": False}
    texts = [c.suggested_open_question or c.message or "" for c in candidates]
    scores, model_id = evidence_relevance_scores(texts, evidence_blob)
    # Hash embedder relevance is noisy — only floor-filter on real neural.
    neural = "deterministic-hash" not in (model_id or "").lower()
    out: list[QuestionCandidate] = []
    kept_scores: list[float] = []
    for c, rel in zip(candidates, scores):
        if neural and rel < NEURAL_RELEVANCE_FLOOR:
            continue
        # Blend prior score with evidence relevance (neural dominates).
        blended = (0.35 * c.score) + (0.65 * max(0.0, min(1.0, rel))) if neural else c.score
        out.append(
            QuestionCandidate(
                rule_id=c.rule_id,
                domain_id=c.domain_id,
                label=c.label,
                severity=c.severity,
                message=c.message,
                suggested_open_question=c.suggested_open_question,
                observed_summary=c.observed_summary,
                source=c.source,
                score=blended,
                evidence_atom_ids=list(c.evidence_atom_ids),
                evidence_sources=list(c.evidence_sources),
                project_mode=c.project_mode,
            )
        )
        kept_scores.append(rel)
    meta = {
        "neural_relevance": neural,
        "neural_relevance_model": model_id,
        "neural_relevance_floor": NEURAL_RELEVANCE_FLOOR if neural else None,
        "neural_relevance_dropped": max(0, len(candidates) - len(out)),
        "neural_relevance_top": round(max(kept_scores), 4) if kept_scores else None,
    }
    return out, meta


def rank_and_cap(
    candidates: list[QuestionCandidate],
    *,
    cap: int = DEFAULT_QUESTION_CAP,
    evidence_blob: str = "",
) -> tuple[list[QuestionCandidate], dict[str, Any]]:
    """Fingerprint → neural evidence score → neural near-dup → rank + cap."""

    def sort_key(c: QuestionCandidate) -> tuple:
        return (
            SEVERITY_SORT.get(c.severity, 9),
            -c.score,
            0 if c.source in {"evidence", "pm_gold"} else 1 if c.source == "mode_template" else 2,
            c.suggested_open_question,
        )

    # Exact fingerprint collapse first (cheap).
    best: dict[str, QuestionCandidate] = {}
    for c in candidates:
        fp = fingerprint_question(c.suggested_open_question or c.message)
        if not fp:
            continue
        prev = best.get(fp)
        if prev is None or _candidate_rank_tuple(c) > _candidate_rank_tuple(prev):
            best[fp] = c

    uniq = list(best.values())
    relevance_meta: dict[str, Any] = {"neural_relevance": False}
    if evidence_blob.strip():
        uniq, relevance_meta = _apply_neural_evidence_scores(uniq, evidence_blob=evidence_blob)
        if not uniq:
            # Never return empty — fall back to pre-filter set.
            uniq = list(best.values())
            relevance_meta["neural_relevance_fallback"] = "empty_after_floor"
    # Neural / embedding near-duplicate clustering (paraphrase collapse).
    deduped, cluster_meta = semantic_dedupe(
        uniq,
        text_fn=lambda c: c.suggested_open_question or c.message or "",
        score_fn=_candidate_rank_tuple,
    )
    ranked = sorted(deduped, key=sort_key)
    # Neural MMR: greedily keep high-score asks that stay diverse (≥0.70 apart).
    selected = _neural_mmr_select(ranked, cap=max(1, cap))
    meta = {
        "semantic_dedupe_input": cluster_meta.input_count,
        "semantic_dedupe_output": cluster_meta.output_count,
        "semantic_dedupe_merged_pairs": cluster_meta.merged_pairs,
        "semantic_dedupe_embedder": cluster_meta.embedder_model,
        "semantic_dedupe_cosine_threshold": cluster_meta.cosine_threshold,
        "mmr_selected": len(selected),
        **relevance_meta,
    }
    return selected, meta


def _neural_mmr_select(
    ranked: list[QuestionCandidate],
    *,
    cap: int,
    diversity_cosine: float = 0.70,
    precomputed_vecs: list[list[float]] | None = None,
) -> list[QuestionCandidate]:
    """Keep top asks while dropping near-neighbors of already-selected ones."""
    if len(ranked) <= cap:
        return ranked
    emb = resolve_question_embedder()
    if not is_neural_embedder(emb) and precomputed_vecs is None:
        return ranked[:cap]
    vecs = precomputed_vecs
    if vecs is None or len(vecs) != len(ranked):
        texts = [c.suggested_open_question or c.message or "" for c in ranked]
        try:
            vecs = emb.embed(texts)
        except Exception:
            return ranked[:cap]
    picked: list[int] = []
    for i, _c in enumerate(ranked):
        if len(picked) >= cap:
            break
        if any(cosine_similarity(vecs[i], vecs[j]) >= diversity_cosine for j in picked):
            continue
        picked.append(i)
    if len(picked) < cap:
        for i in range(len(ranked)):
            if i in picked:
                continue
            picked.append(i)
            if len(picked) >= cap:
                break
    return [ranked[i] for i in picked]


def build_customer_questions(
    *,
    gaps: list[GapCard],
    sites: list[SiteSummary],
    envelope: Mapping[str, Any] | None = None,
    report: Mapping[str, Any] | None = None,
    feedback_events: Iterable[QuestionFeedbackEvent] | None = None,
    feedback_policy: FeedbackPolicy | None = None,
    case_dir: Any = None,
    cap: int = DEFAULT_QUESTION_CAP,
) -> tuple[list[GapCard], dict[str, Any]]:
    """Build the curated customer_questions list + debug meta."""
    atoms = _atoms_from_sources(envelope, report)
    blob = _blob_from_atoms(atoms)
    service_routing = None
    pack_prior = None
    if isinstance(envelope, Mapping):
        service_routing = envelope.get("service_routing")
    if isinstance(report, Mapping):
        pack_prior = report.get("pack_prior")
        if service_routing is None and isinstance(report.get("service_routing"), Mapping):
            service_routing = report.get("service_routing")

    project_mode = detect_project_mode(
        atoms=atoms,
        service_routing=service_routing if isinstance(service_routing, Mapping) else None,
        pack_prior=pack_prior if isinstance(pack_prior, Mapping) else None,
        blob=blob,
    )

    if feedback_policy is None:
        events = list(feedback_events) if feedback_events is not None else load_feedback(case_dir=case_dir)
        feedback_policy = compile_feedback_policy(events)

    docs_by_id = _docs_by_artifact_id(envelope if isinstance(envelope, Mapping) else None)

    candidates: list[QuestionCandidate] = []
    candidates.extend(
        _candidates_from_evidence_atoms(
            atoms,
            project_mode=project_mode,
            evidence_blob=blob,
            docs_by_id=docs_by_id,
        )
    )
    candidates.extend(
        _candidates_from_mode_templates(
            project_mode=project_mode,
            blob=blob,
            atoms=atoms,
            docs_by_id=docs_by_id,
        )
    )
    candidates = suppress_answered(candidates, blob=blob, sites=sites)
    candidates = apply_feedback(candidates, feedback_policy, project_mode=project_mode)

    # Never promote banned ops families on install mode even if they leaked in
    if project_mode == MODE_NETWORK_EDGE_INSTALL:
        candidates = [
            c
            for c in candidates
            if not any(c.rule_id.startswith(p) for p in _INSTALL_BANNED_RULE_PREFIXES)
        ]

    existing = {c.rule_id for c in candidates}
    # Safety-net only when evidence/mode produced too few asks
    if len(candidates) < MIN_SAFETY_NET_IF_EMPTY:
        for g_cand in _yaml_safety_net(
            gaps,
            project_mode=project_mode,
            existing_rule_ids=existing,
            max_add=MIN_SAFETY_NET_IF_EMPTY,
        ):
            grounded = _with_evidence(
                g_cand, atoms=atoms, docs_by_id=docs_by_id, require=False
            )
            if grounded is not None:
                candidates.append(grounded)

    # Attach / refresh pointed photo citations (where + what in frame).
    grounded_all: list[QuestionCandidate] = []
    for c in candidates:
        require = c.source in {"mode_template", "evidence", "yaml_safety"} and not c.evidence_sources
        g = _with_evidence(c, atoms=atoms, docs_by_id=docs_by_id, require=require)
        if g is not None:
            grounded_all.append(g)
    candidates = grounded_all

    ranked, dedupe_meta = rank_and_cap(candidates, cap=cap, evidence_blob=blob)
    # Final containment: never ship smalltalk / meta even if an atom slipped
    # past type gates (e.g. mis-typed open_question).
    ranked = [
        c
        for c in ranked
        if _is_customer_facing_question(c.suggested_open_question or c.message or "")
    ]
    # Triple-check: drop any ask that still has zero matching sources
    # (except rare PM-gold teaching rows).
    ranked = [
        c
        for c in ranked
        if c.evidence_sources or c.source == "pm_gold"
    ]
    cards = [c.to_gap_card() for c in ranked]
    meta = {
        "project_mode": project_mode,
        "candidate_count_before_cap": len(candidates),
        "sources": {
            "evidence": sum(1 for c in ranked if c.source == "evidence"),
            "mode_template": sum(1 for c in ranked if c.source == "mode_template"),
            "yaml_safety": sum(1 for c in ranked if c.source == "yaml_safety"),
            "pm_gold": sum(1 for c in ranked if c.source == "pm_gold"),
        },
        "with_citations": sum(1 for c in ranked if c.evidence_sources),
        "cap": cap,
        "suppressed_rule_ids": sorted(feedback_policy.suppressed_rule_ids)[:40],
        **dedupe_meta,
    }
    return cards, meta
