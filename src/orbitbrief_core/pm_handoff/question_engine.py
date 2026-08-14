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
from dataclasses import asdict, dataclass, field
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
    embedder_health as _embedder_health,
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

# PM Review Queue shortlist size. Env-tunable so queue depth can be dialed
# without a redeploy — every real deal saturates this cap, so it is the single
# knob deciding how much of the known work a PM can actually see.
DEFAULT_QUESTION_CAP = int(__import__("os").environ.get("ORBITBRIEF_QUESTION_CAP", "12"))
# Evidence-ranked audit pool (not dumped into the PM Review Queue).
DEFAULT_QUESTION_POOL_CAP = int(
    __import__("os").environ.get("ORBITBRIEF_QUESTION_POOL_CAP", "50")
)
MIN_SAFETY_NET_IF_EMPTY = 2
# Drop candidates whose neural relevance to deal evidence falls below this.
# Raised from 0.28 — weak generic / off-mode asks were leaking into the shortlist.
NEURAL_RELEVANCE_FLOOR = float(
    __import__("os").environ.get("ORBITBRIEF_QUESTION_NEURAL_FLOOR", "0.36")
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
MODE_ASSESSMENT = "security_assessment"
MODE_DECOM = "decommission_logistics"
MODE_GENERIC = "generic"


# Router pack -> project mode. The router (neural head, or the LLM scope
# classifier behind it) decides WHICH workstream a deal is; this table is the
# only place that decision becomes a mode. Packs absent here have no dedicated
# question set, so they fall through to the evidence cascade below.
_MODE_BY_PACK: dict[str, str] = {
    "staff_augmentation": MODE_STAFF_AUG,
    "wireless": MODE_WIRELESS_INSTALL,
    "low_voltage_cabling": MODE_CABLING,
    "cabling": MODE_CABLING,
    "audio_visual": MODE_AV,
    "network_maintenance": MODE_NETWORK_OPS,
    "alm": MODE_ALM,
    "security_access": MODE_ACCESS,
}

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
    MODE_ASSESSMENT: frozenset({"global", "commercial", "project", "hardware"}),
    MODE_DECOM: frozenset({"global", "commercial", "hardware", "site", "project"}),
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
    r"\b(?:"
    r"staff\s+aug(?:mentation)?|resource\s+surge|1099|"
    r"cleared\s+resource|badged\s+resource|"
    r"local\s+resource|quote\s+me\s+by\s+the\s+day|billing\s+type:\s*per\s+day|"
    r"per[\-\s]?day\s+(?:rate|resource|tech)|day[\-\s]?rate\s+resource"
    r")\b",
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
    r"hdmi\s+replicator|behind\s+the\s+wall|room\s+bar|"
    r"display\s+mount|tv\s+mount|wall\s+mount\b|ceiling\s+mount"
    r")\b",
    re.I,
)
_FLOOR_PATHWAY_EVIDENCE_RE = re.compile(
    r"\b(?:receptacle|floor\s+box|poke[\-\s]?through|"
    r"across\s+the\s+floor|cable(?:s)?\s+(?:run|across|visible).{0,40}floor|"
    r"floor.{0,40}(?:network|receptacle|cable)|10\s*(?:ft|feet)|"
    r"network\s+(?:path|run|port|connectivity).{0,40}floor|"
    r"floor.{0,40}network\s+(?:path|run|connectivity|receptacle))\b",
    re.I,
)
_KEEP_TV_ANNOTATION_RE = re.compile(
    r"\b(?:tvs?\s+to\s+stay|stay\s+in\s+place|remain\s+on\s+(?:floor|vesa|mount))\b",
    re.I,
)
_ACCESS_RE = re.compile(
    r"\b(?:access\s+control|card\s+reader|door\s+controller|maglock|electric\s+strike)\b",
    re.I,
)
# Cloud / pentest / security assessment — must beat mis-routed access_control.
_ASSESSMENT_RE = re.compile(
    r"\b(?:"
    r"penetrat(?:ion)?\s+test|pentest|"
    r"vulnerab(?:ility)?\s+(?:assess|scan|test)|"
    r"red\s+team|rules?\s+of\s+engagement|"
    r"azure\s+(?:ad|backup|migrate|region)|entra\s+id|"
    r"conditional\s+access|immutable\s+(?:storage|blob)|"
    r"security\s+assessment|black[\-\s]?box|grey[\-\s]?box|white[\-\s]?box|"
    r"backup\s+vault|data[\-\s]?movement\s+method"
    r")\b",
    re.I,
)
_DECOM_RE = re.compile(
    r"\b(?:iron\s+mountain|de[\-\s]?rack|pack(?:ing)?\s*/?\s*prep for shipping|"
    r"palletize|shrink\s+wrap|return\s+shipping|equipment for (?:pickup|disposal)|"
    r"onsite inventory verification)\b",
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
    # Floor-path asks: prefer cable/receptacle/floor-box facts over keep-TV notes.
    # Live Catalyst annotations often pack BOTH "TVs stay" and the 10ft floor path
    # in one blob — still demote the keep-TV framing so the cable fact wins first.
    q_low = (question or "").lower()
    if "floor" in q_low and ("path" in q_low or "raceway" in q_low or "receptacle" in q_low):
        if _FLOOR_PATHWAY_EVIDENCE_RE.search(text):
            score += 0.16
        if "cable" in fk or fk.endswith(":cable") or "floor" in fk:
            score += 0.14
        if _KEEP_TV_ANNOTATION_RE.search(text):
            score -= 0.34
    # Triple-check: if trigger exists, require trigger OR strong keyword overlap.
    if trigger is not None and not trig_hit and len(q_toks & a_toks) < 3:
        return 0.0
    # Allow >1.0 so relative ranking survives (display still rounds).
    return max(0.0, min(1.5, score))


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
    min_score: float | None = None,
) -> QuestionCandidate | None:
    """Attach matching sources; drop candidate when require=True and nothing matches."""
    atom_list = [a for a in atoms if isinstance(a, Mapping)]
    # A candidate that NAMES its evidence is grounded by that evidence.
    #
    # Only evidence_sources was honoured here, so a candidate carrying verified
    # evidence_atom_ids fell through to _collect_matching_evidence and was
    # re-grounded by text similarity against a 0.42 gate -- the citations were
    # discarded and re-derived. For generated exposure questions that is both
    # wrong and unstable: the model cites the rate-card line that makes the
    # question necessary, while the matcher scores the question's own wording
    # against atom text. Measured on Clayton, the same 8 candidates published
    # 2, then 1, then 0 across three runs purely on which side of the gate the
    # re-match landed, and a question that survived could be attributed to an
    # atom it never cited.
    #
    # Resolving the cited ids directly makes grounding exact and deterministic.
    # It cannot weaken the contract: question_llm already validates every id
    # against the real atom set and drops uncited questions.
    if not candidate.evidence_sources and candidate.evidence_atom_ids:
        cited_by_id = _atoms_by_id(atom_list)
        cited_srcs: list[dict[str, Any]] = []
        cited_ids: list[str] = []
        for aid in candidate.evidence_atom_ids:
            atom = cited_by_id.get(str(aid))
            if atom is None:
                continue
            cited_srcs.append(
                _source_from_atom(
                    atom,
                    _atom_evidence_text(atom),
                    score=1.0,  # an explicit citation is not a similarity guess
                    docs_by_id=docs_by_id,
                    atoms_by_id=cited_by_id,
                )
            )
            cited_ids.append(str(aid))
        if cited_srcs:
            from dataclasses import replace as _replace

            return _replace(
                candidate,
                evidence_atom_ids=cited_ids,
                evidence_sources=cited_srcs,
                observed_summary=_pointed_observed(cited_srcs)
                or candidate.observed_summary,
            )
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
    floorish = "floor_network_path" in (candidate.rule_id or "")
    gate = 0.30 if floorish and min_score is None else (0.42 if min_score is None else min_score)
    sources, ids, observed = _collect_matching_evidence(
        atom_list,
        question=candidate.suggested_open_question or candidate.message or candidate.label,
        trigger=trigger,
        docs_by_id=docs_by_id,
        min_score=gate,
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
    """Evidence text + locator section paths (SOW 'Out of Scope' lives here)."""
    parts: list[str] = []
    for a in atoms:
        if not isinstance(a, Mapping):
            continue
        t = (_atom_text(a) or "").strip()
        if t:
            parts.append(t)
        loc = a.get("locator") if isinstance(a.get("locator"), Mapping) else {}
        sp = loc.get("section_path") if isinstance(loc, Mapping) else None
        if isinstance(sp, list) and sp:
            parts.append(" / ".join(str(x) for x in sp if str(x).strip()))
        elif isinstance(sp, str) and sp.strip():
            parts.append(sp.strip())
    return "\n".join(parts)


def _deal_header_blob(envelope: Mapping[str, Any] | None) -> str:
    """Structured customer / opportunity labels for cross-deal flavor pins."""
    if not isinstance(envelope, Mapping):
        return ""
    dh = envelope.get("deal_header")
    if not isinstance(dh, Mapping):
        return ""
    fields = dh.get("fields")
    lines: list[str] = []
    if isinstance(fields, Mapping):
        for key in (
            "customer",
            "end_user",
            "opportunity_id",
            "account",
            "company",
            "segment",
            "division",
        ):
            val = fields.get(key)
            if val is not None and str(val).strip():
                lines.append(f"{key}: {str(val).strip()}")
        # Any remaining string fields (low priority).
        for key, val in fields.items():
            if key in {"customer", "end_user", "opportunity_id", "account", "company"}:
                continue
            if val is not None and str(val).strip() and len(lines) < 16:
                lines.append(f"{key}: {str(val).strip()}")
    return "\n".join(lines)


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

    text_s = text or ""
    av_strong_n = len(_AV_STRONG_RE.findall(text_s))
    decom_n = len(_DECOM_RE.findall(text_s))

    # The router already answered this question. Everything below answers it a
    # second time from vocabulary, and used to win: measured over 20 live deals,
    # giving the cascade a perfect router moved accuracy only 25% -> 35%,
    # because thirteen of the fifteen errors were settled before the router's
    # pack was ever consulted.
    #
    # So the router's pack maps straight to its mode, with NO lexicon veto.
    # Both vetoes were measured and both lose to the router:
    #   * dense AV vocabulary overrode it on 4 of 20 deals and was wrong on all
    #     4 -- a cabling job that mentions displays is still a cabling job
    #     (15/20 with the veto, 19/20 without);
    #   * decommission vocabulary overrode it on nyc_migration, a cabling job
    #     that legitimately says "de-rack" and "shrink wrap" twelve times
    #     (19/20 with it, 20/20 without).
    # Both checks still run below for deals where the router abstains, which is
    # most of them -- the head is a specialist over four packs by design.
    # Density floor for letting vocabulary override a router answer whose pack
    # has no bespoke mode. Measured 2026-08-13 (strong AV+wireless hits per 10k
    # chars of atom text):
    #     test_an_unmapped_pack_falls_through  ......  2.0   (59 chars, decisive)
    #     paulweiss  (router said telecom)  .........  0.3   (250k chars)
    #     la_relocation (router said data_migration)   0.3   (309k chars)
    #     oxblue (router said security_camera) ......  0.0   (256k chars)
    # Three mentions of a display in a 250k-char corpus is not evidence that a
    # Cisco voice RFP is an AV job; the same regex on a one-line scope is.
    _UNMAPPED_LEXICON_DENSITY = 1.0

    routed = _MODE_BY_PACK.get(primary)
    if routed is not None:
        # Two refinements the router cannot express, since both are a
        # sub-type of the pack it already chose rather than a different pack.
        if routed == MODE_WIRELESS_INSTALL and _CONFIG_ONLY_RE.search(text_s):
            return MODE_WIRELESS_CONFIG
        if routed == MODE_NETWORK_OPS and _NETWORK_INSTALL_EVIDENCE_RE.search(text_s):
            return MODE_NETWORK_EDGE_INSTALL
        return routed
    if primary:
        # The router answered a pack with no dedicated question set. Falling
        # straight through to vocabulary throws that answer away: measured
        # 2026-08-13, DeepSeek routed a Cisco voice RFP to `telecom` and a Dell
        # relocation to `data_migration` -- both right -- and both became
        # `av_install` off a handful of incidental display mentions in a
        # quarter-million characters.
        #
        # Vocabulary still wins when it is DENSE enough to be decisive, which is
        # what test_an_unmapped_pack_falls_through is really about: a scope that
        # says "install 40 access points and run a wireless heatmap survey" IS a
        # wireless job whatever the router said. Density tells those apart;
        # presence does not.
        # Count every family the cascade below can decide on, not just AV and
        # wireless: a short blob that is decisively an ASSESSMENT (pentest,
        # rules of engagement) must still reach that branch. Counting only two
        # families sent test_assessment_mode_beats_access_control_primary to
        # generic, because its evidence is dense but in a third family.
        _hits = (
            len(_AV_STRONG_RE.findall(text_s))
            + len(_WIRELESS_STRONG_RE.findall(text_s))
            + len(_ASSESSMENT_RE.findall(text_s))
            + len(_ACCESS_RE.findall(text_s))
            + len(_DECOM_RE.findall(text_s))
            + len(_ALM_RE.findall(text_s))
        )
        if _hits / max(1.0, len(text_s) / 10000.0) < _UNMAPPED_LEXICON_DENSITY:
            return MODE_GENERIC

    # ── From here down the router had no opinion, so vocabulary decides. ──

    # Pack-out / Iron Mountain logistics must not inherit AV mode from stray
    # TV mentions.
    if decom_n >= 3 and decom_n >= max(3, av_strong_n):
        return MODE_DECOM

    # Dense conference-room AV evidence wins before incidental SD-WAN / WiFi
    # routing overrides (marketing WiFi must not flip a Neat/Yealink pack).
    if av_strong_n >= 3 or (primary == "audio_visual" and av_strong_n >= 1):
        return MODE_AV

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

    # Weak AV lexicon (e.g. stray "projector") must not beat decommission logistics.
    if _AV_RE.search(text_s) and decom_n < 2:
        return MODE_AV

    assess_hits = len(_ASSESSMENT_RE.findall(text_s))
    door_hits = len(_ACCESS_RE.findall(text_s))
    # Assessment / cloud evidence wins over incidental "Access Control" pack
    # mentions (Azure/pentest SOWs often list ACS as a sibling service line).
    if assess_hits >= 2 and assess_hits >= max(3, door_hits * 3):
        return MODE_ASSESSMENT
    if primary == "access_control" and assess_hits >= 2 and assess_hits >= max(3, door_hits * 3):
        return MODE_ASSESSMENT

    if primary == "access_control" or door_hits >= 1:
        # Still prefer assessment when doors are a thin mention vs dense cloud/pentest.
        if assess_hits >= 5 and door_hits <= 5:
            return MODE_ASSESSMENT
        return MODE_ACCESS

    if assess_hits >= 1:
        return MODE_ASSESSMENT

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
    # Answer leakage / affirmation prefixes are not PM asks.
    if re.match(r"(?i)^(?:yes|no|ok|okay|sure|correct)[,.]?\s+", t):
        return False
    low = t.lower()
    # Markdown / risk-register table rows are not customer questions
    # (e.g. "| R2 | **TSA-badged escort… | High | Med | … |?").
    if t.count("|") >= 3:
        return False
    if re.search(r"\|\s*r\d+\s*\|", low) or re.search(r"\bhigh\s*\|\s*med(?:ium)?\b", low):
        return False
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
        "drum up a local resource",
        "kyle copied here",
        "let our lead engineer",
        "loose from our onsite",
    )
    if any(b in low for b in banned):
        return False
    if _SMALLTALK_RE.search(low):
        return False
    # Lazy Confirm-paste / Include-wrap of raw SOW/email prose is not a PM ask.
    if re.match(
        r"(?i)^(?:confirm\s+(?:customer\s+instruction|pricing\s+assumption|"
        r"this\s+is\s+in-scope|this\s+requirement\s+is\s+binding|"
        r"how\s+this\s+risk|bom\s+line|this\s+stays\s+excluded|"
        r"this\s+pricing/scope\s+assumption)|"
        r"include\s+in\s+this\s+quote,\s+or\s+exclude|"
        r"is\s+this\s+a\s+binding\s+requirement)\b",
        t,
    ):
        return False
    if "…" in t or t.rstrip().endswith("..."):
        return False
    if re.search(r"(?i)https?://|hs-sales-engage|/ctc/", t):
        return False
    if re.search(
        r"(?i)\b(?:hope\s+(?:you|my\s+email)|great\s+start\s+to\s+the\s+week|"
        r"don'?t\s+hesitate|thank\s+you\s+so\s+much|draw\s+up\s+a\s+quote|"
        r"material\s+breach|form\s+w-?9|either\s+party\s+may\s+terminate|"
        r"total\s+fees|draft\s+intended|knowledgeable\s+resource|"
        r"awesome\.?\s+appreciate|no\s+worries\s+at\s+all|"
        r"every\s+billable\s+device|"
        r"who\s+must\s+be\s+on\s+the\s+customer\s+thread|"
        r"operations\s+must\s+be\s+involved\s+early)\b",
        low,
    ):
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
    r"(?:may|could|might)\s+pose|(?:may|could|might)\s+affect|may\s+impact|"
    r"potentially\s+affecting|slight\s+trip|"
    r"patterned\s+carpet|non[\-\s]?standard\s+tile|field\s+of\s+view|"
    r"\baesthetic\b|professional\s+appearance|cleaner\s+look|not\s+fully\s+conceal|"
    r"trip\s+hazard|"
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
            "missing_info",
            "gap",
        }:
            # action_item only when already a question; never promote raw risk rows
            if atype == "action_item":
                text_probe = _atom_question_text(atom)
                if "?" not in text_probe and not re.match(
                    r"(?i)^(?:confirm|which|who|what|can\s+we)\b", text_probe.strip()
                ):
                    continue
            else:
                # Also accept scope_item / constraint that are clearly questions
                text_probe = _atom_question_text(atom)
                if "?" not in text_probe and not text_probe.lower().startswith("once we know"):
                    continue
        text = _atom_question_text(atom)
        if not _is_customer_facing_question(text):
            continue
        # Labeled atom dumps ("RISKS: …") are observations, not PM asks.
        # Mode templates own the curated wording when evidence collides.
        if re.match(r"^(?:risks?|facts?|notes?|issues?)\s*:\s*", text, re.I):
            continue
        if atype == "risk":
            continue
        # A roster row is data, not a gap. Un-truncating the inspection report
        # made all 438 of Clayton's site rows visible to this generator, and it
        # turned each one into a question: "evidence.site_roster.1007 clayton
        # homes of augusta flg cla traditional r...". They were suppressed
        # downstream, but they pushed candidates 92 -> 148 and crowded the funnel
        # that MMR and the 12-slot cap select from — the fix for one blindness
        # created noise in its place. Roster/site rows describe WHERE the work
        # is, and the site generators already ask about that properly.
        if atype in {"site_roster", "physical_site", "site_attribute", "address"}:
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
        severity = "blocker" if atype in {"missing_info", "gap"} else "warning"
        # Prefer open_question / decision; demote still-casual rewrites slightly
        score = 0.92 if atype == "open_question" else 0.85 if atype == "decision" else 0.72
        if atype == "action_item" and "sop" in pm_q.lower():
            score = 0.94
        if "sop" in pm_q.lower() and atype == "open_question":
            score = 0.96
        if pm_q != text and atype == "open_question":
            score = max(score, 0.9)
        label = {
            "open_question": "Open project question",
            "decision": "Decision still open",
            "missing_info": "Missing information",
            "gap": "Scope gap",
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
    # Do NOT turn observations into questions by appending "?".
    # Only keep already-decision-shaped prose; otherwise drop.
    if re.match(
        r"(?i)^(?:confirm|decide|clarify|which|who|what|when|where|how|"
        r"is\s+it|are\s+we|can\s+we|do\s+we|should)\b",
        t,
    ):
        if not t.endswith("?"):
            t = t.rstrip(".") + "?"
        return t[0].upper() + t[1:] if t and t[0].islower() else t
    return ""


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
                r"\b(?:access\s+points?|wlan\s+install|wireless\s+install|ssid|heatmap|\baps?\b)\b",
                re.I,
            ),
            # Count alone is not a lock — need count + OEM/model language.
            answered_by=re.compile(
                r"(?i)\b\d+\s*(?:x\s*)?(?:aps?|access\s+points?)\b.{0,48}"
                r"(?:meraki|cisco|aruba|ruckus|omada|unifi|model)",
            ),
            severity="blocker",
            score=0.93,
        ),
        _ModeTemplate(
            rule_id="mode.wireless_install.cable_vs_swap",
            domain_id="wireless",
            label="Cable vs 1-for-1 swap",
            question="Is AP work new cable pulls, or a 1-for-1 swap on existing drops?",
            message="Cable-vs-swap is still open for wireless install.",
            trigger=re.compile(r"(?i)\b(?:1\s*for\s*1|like[\-\s]?for[\-\s]?like|run\s+cable|home\s+run|\baps?\b)\b"),
            severity="blocker",
            score=0.94,
        ),
        _ModeTemplate(
            rule_id="mode.wireless_install.lift_vs_ladder",
            domain_id="wireless",
            label="Lift vs ladder",
            question="Confirm ceiling access method for AP work — ladder-only or lift required?",
            message="Ceiling height / lift need is unsettled.",
            trigger=re.compile(r"(?i)\b(?:ceiling|lift|ladder|scissor)\b"),
            severity="warning",
            score=0.88,
        ),
        _ModeTemplate(
            rule_id="mode.wireless_install.controller_adopt",
            domain_id="wireless",
            label="Controller / adoption",
            question="Who adopts APs onto the controller / cloud — PurTera or customer NOC — and what tenant?",
            message="AP adoption ownership unset.",
            trigger=re.compile(r"(?i)\b(?:controller|adopt|meraki|omada|unifi|cisco|ssid|wlan)\b"),
            severity="warning",
            score=0.86,
        ),
        _ModeTemplate(
            rule_id="mode.wireless_install.survey_first",
            domain_id="wireless",
            label="Survey before quote",
            question="Is a fresh site survey required before final quote, or is the prior walkthrough sufficient?",
            message="Survey-vs-prior-walkthrough is open.",
            trigger=re.compile(r"(?i)\b(?:site\s+survey|walkthrough|send someone|take a look)\b"),
            severity="warning",
            score=0.85,
        ),
        _ModeTemplate(
            rule_id="mode.wireless_install.ap_stick",
            domain_id="wireless",
            label="AP-on-a-Stick survey",
            question="Is AP-on-a-Stick survey in this quote for select sites, allowance, or customer-owned?",
            message="AP-on-a-Stick survey commercial model unset.",
            trigger=re.compile(
                r"(?i)\b(?:ap\s+on\s+a\s+stick|ap[\-\s]?on[\-\s]?a[\-\s]?stick|"
                r"site\s+survey|heatmap|predictive|walkthrough)\b"
            ),
            severity="warning",
            score=0.84,
        ),
        _ModeTemplate(
            rule_id="mode.wireless_install.design_owner",
            domain_id="wireless",
            label="Wireless design ownership",
            question="Who owns final wireless design / analysis / reporting — PurTera or customer partner?",
            message="Wireless design ownership unset.",
            trigger=re.compile(
                r"(?i)\b(?:wireless\s+design|heatmap|rf\s+design|predictive|"
                r"ssid|wlan|meraki|access\s+point)\b"
            ),
            severity="warning",
            score=0.83,
        ),
        _ModeTemplate(
            rule_id="mode.wireless_install.poe_switch",
            domain_id="wireless",
            label="PoE / switch readiness",
            question="Confirm PoE budget / switch port readiness for every new AP drop — customer or PurTera?",
            message="PoE / switch readiness unset.",
            trigger=re.compile(r"(?i)\b(?:poe|switch\s+port|power\s+over\s+ethernet|vlan)\b"),
            severity="warning",
            score=0.82,
        ),
        _ModeTemplate(
            rule_id="mode.wireless_install.mount_reuse",
            domain_id="wireless",
            label="Mount / drop reuse",
            question="Confirm existing AP mounts/drops are reused — or quote new mounts and home runs?",
            message="Mount/drop reuse unset.",
            trigger=re.compile(r"(?i)\b(?:mount|home\s+run|drop|access\s+point|\baps?\b)\b"),
            severity="warning",
            score=0.81,
        ),
        _ModeTemplate(
            rule_id="mode.wireless_install.ssid_cutover",
            domain_id="wireless",
            label="SSID cutover window",
            question="When does SSID / VLAN cutover happen relative to AP swap — same visit or staged?",
            message="SSID cutover sequencing unset.",
            trigger=re.compile(r"(?i)\b(?:ssid|vlan|cutover|swap|wireless)\b"),
            severity="warning",
            score=0.8,
        ),
        _ModeTemplate(
            rule_id="mode.wireless_install.spare_aps",
            domain_id="wireless",
            label="Spare AP stocking",
            question="Are spare APs / mounts stocked in this quote, or RMA-only if a unit fails?",
            message="Spare AP stocking unset.",
            trigger=re.compile(r"(?i)\b(?:spare|rma|access\s+point|\baps?\b|meraki|cisco)\b"),
            severity="warning",
            score=0.79,
        ),
        _ModeTemplate(
            rule_id="mode.wireless_install.channel_plan",
            domain_id="wireless",
            label="Channel / power plan",
            question="Confirm RF channel / TX-power plan ownership — PurTera design or customer WLAN team?",
            message="RF channel plan ownership unset.",
            trigger=re.compile(r"(?i)\b(?:channel|tx\s*power|rf|wlan|wireless|ssid)\b"),
            severity="warning",
            score=0.78,
        ),
        _ModeTemplate(
            rule_id="mode.wireless_install.cable_cat",
            domain_id="wireless",
            label="Cable category",
            question="Confirm cable category / plenum rating for any new AP drops in this quote.",
            message="Cable category unset.",
            trigger=re.compile(r"(?i)\b(?:cat\s*[56]|plenum|cable|home\s+run|drop)\b"),
            severity="warning",
            score=0.78,
        ),
        _ModeTemplate(
            rule_id="mode.wireless_install.patch_panel",
            domain_id="wireless",
            label="Patch panel / switch landing",
            question="Where do new AP home runs land — existing patch panel, new panel, or switch directly?",
            message="AP home-run landing unset.",
            trigger=re.compile(
                r"(?i)\b(?:patch\s+panel|home\s+run|switch|idf|mdf|access\s+point|\baps?\b|meraki|cable)\b"
            ),
            severity="warning",
            score=0.77,
        ),
        _ModeTemplate(
            rule_id="mode.wireless_install.labeling",
            domain_id="wireless",
            label="AP labeling standard",
            question="Confirm AP / drop labeling standard required before handoff.",
            message="AP labeling standard unset.",
            trigger=re.compile(r"(?i)\b(?:label|as[\-\s]?built|hand\s*off|access\s+point|\baps?\b)\b"),
            severity="warning",
            score=0.76,
        ),
        _ModeTemplate(
            rule_id="mode.wireless_install.old_gear",
            domain_id="wireless",
            label="Old AP disposition",
            question="Confirm disposition of removed APs — leave onsite, return to customer, or PurTera dispose?",
            message="Removed AP disposition unset.",
            trigger=re.compile(r"(?i)\b(?:remove|replaced|old\s+ap|existing\s+ap|swap)\b"),
            severity="warning",
            score=0.76,
        ),
        _ModeTemplate(
            rule_id="mode.wireless_install.floor_plans",
            domain_id="wireless",
            label="Floor plan authority",
            question="Who provides authoritative floor plans / AP maps before mobilization?",
            message="Floor plan authority unset.",
            trigger=re.compile(r"(?i)\b(?:floor\s+plan|ap\s+map|heatmap|drawing|markup)\b"),
            severity="warning",
            score=0.75,
        ),
        _ModeTemplate(
            rule_id="mode.wireless_install.work_hours",
            domain_id="wireless",
            label="Install work hours",
            question="Confirm AP install stays in business hours — any after-hours premium sites?",
            message="Install work hours unset.",
            trigger=re.compile(r"(?i)\b(?:business\s+hours|after[\-\s]?hours|access\s+point|install)\b"),
            severity="warning",
            score=0.75,
        ),
        _ModeTemplate(
            rule_id="mode.wireless_install.staging",
            domain_id="wireless",
            label="AP staging / config",
            question="Are APs staged/pre-configured before site, or configured onsite after mount?",
            message="AP staging model unset.",
            trigger=re.compile(r"(?i)\b(?:stage|pre[\-\s]?config|adopt|claim|meraki|cisco)\b"),
            severity="warning",
            score=0.74,
        ),
        _ModeTemplate(
            rule_id="mode.wireless_install.coverage_test",
            domain_id="wireless",
            label="Coverage acceptance test",
            question="What coverage / speed test is the pass/fail acceptance for each site?",
            message="Wireless acceptance test unset.",
            trigger=re.compile(r"(?i)\b(?:coverage|acceptance|speed\s+test|survey|ssid)\b"),
            severity="warning",
            score=0.74,
        ),
        _ModeTemplate(
            rule_id="mode.wireless_install.guest_ssid",
            domain_id="wireless",
            label="Guest SSID / isolation",
            question="Confirm guest SSID scope and isolation — in this wave, deferred, or customer-owned?",
            message="Guest SSID / isolation unset.",
            trigger=re.compile(r"(?i)\b(?:guest|ssid|vlan|wireless|wlan|isolation)\b"),
            severity="warning",
            score=0.73,
        ),
        _ModeTemplate(
            rule_id="mode.wireless_install.radius_nac",
            domain_id="wireless",
            label="RADIUS / NAC source",
            question="What RADIUS/NAC source authenticates corporate Wi‑Fi — and who owns cert/profile push?",
            message="RADIUS/NAC ownership unset.",
            trigger=re.compile(r"(?i)\b(?:radius|nac|802\.1x|ssid|wireless|meraki|cisco)\b"),
            severity="warning",
            score=0.73,
        ),
        _ModeTemplate(
            rule_id="mode.wireless_install.cable_path",
            domain_id="wireless",
            label="New-drop pathway",
            question="For any new AP drops, who owns pathway (conduit/raceway) — customer/GC or PurTera?",
            message="New AP drop pathway ownership unset.",
            trigger=re.compile(r"(?i)\b(?:pathway|conduit|raceway|home\s+run|cable|drop|ap)\b"),
            severity="warning",
            score=0.72,
        ),
        _ModeTemplate(
            rule_id="mode.wireless_install.wave_lock",
            domain_id="wireless",
            label="Wave / site lock",
            question="Confirm which sites are in this install wave — any adds/drops before mobilize?",
            message="Wireless install wave / site lock unset.",
            trigger=re.compile(r"(?i)\b(?:site|wave|phase|rollout|access\s+point|meraki|wireless)\b"),
            severity="warning",
            score=0.72,
        ),
        _ModeTemplate(
            rule_id="mode.wireless_install.escalation",
            domain_id="project",
            label="Day-of escalation",
            question="Who is the customer escalation contact if an AP site is blocked on arrival?",
            message="Wireless day-of escalation unset.",
            trigger=re.compile(r"(?i)\b(?:escalat|contact|onsite|access\s+point|install|site)\b"),
            severity="warning",
            score=0.71,
        ),
        _ModeTemplate(
            rule_id="mode.wireless_install.as_built",
            domain_id="wireless",
            label="As-built deliverable",
            question="Are as-built AP maps / photos in the fixed fee — and who archives them?",
            message="Wireless as-built deliverable unset.",
            trigger=re.compile(r"(?i)\b(?:as[\-\s]?built|photo|map|documentation|hand\s*off|ap)\b"),
            severity="warning",
            score=0.71,
        ),
        _ModeTemplate(
            rule_id="mode.wireless_install.license",
            domain_id="wireless",
            label="AP licenses",
            question="Confirm AP licenses / cloud claims are customer-owned before install day.",
            message="AP license ownership unset.",
            trigger=re.compile(r"(?i)\b(?:license|claim|adopt|meraki|cisco|cloud|controller)\b"),
            severity="warning",
            score=0.7,
        ),
        _ModeTemplate(
            rule_id="mode.wireless_install.idf_access",
            domain_id="site",
            label="IDF / MDF access",
            question="Confirm IDF/MDF access hours and escort for every AP home-run landing site.",
            message="IDF/MDF access unset.",
            trigger=re.compile(r"(?i)\b(?:idf|mdf|closet|patch|switch|access|escort|ap)\b"),
            severity="warning",
            score=0.7,
        ),
    ),
    MODE_WIRELESS_CONFIG: (
        _ModeTemplate(
            rule_id="mode.wireless_config.ssid_vlan",
            domain_id="wireless",
            label="SSID / VLAN map",
            question="Confirm SSID → VLAN / firewall policy map that PurTera must configure.",
            message="SSID/VLAN mapping unset for wireless config.",
            trigger=re.compile(r"(?i)\b(?:ssid|vlan|wireless|wlan)\b"),
            severity="blocker",
            score=0.9,
        ),
        _ModeTemplate(
            rule_id="mode.wireless_config.radius",
            domain_id="wireless",
            label="RADIUS / 802.1X",
            question="Confirm RADIUS / 802.1X / captive-portal requirements PurTera must configure.",
            message="Wireless auth backend unset.",
            trigger=re.compile(r"(?i)\b(?:radius|802\.1x|captive|nac|ise)\b"),
            severity="warning",
            score=0.86,
        ),
        _ModeTemplate(
            rule_id="mode.wireless_config.guest",
            domain_id="wireless",
            label="Guest SSID scope",
            question="Is guest / contractor SSID in this config wave, or deferred?",
            message="Guest SSID scope unset.",
            trigger=re.compile(r"(?i)\b(?:guest\s+ssid|contractor|captive)\b"),
            severity="warning",
            score=0.84,
        ),
    ),
    MODE_CABLING: (
        _ModeTemplate(
            rule_id="mode.cabling.cat_rating",
            domain_id="low_voltage_cabling",
            label="Cable category / plenum",
            question="Confirm cable category and plenum vs non-plenum rating required for new drops.",
            message="Cable rating unset.",
            trigger=re.compile(r"(?i)\b(?:cat\s*[56]|plenum|cable\s+drop|home\s+run)\b"),
            severity="blocker",
            score=0.9,
        ),
    ),
    MODE_DECOM: (
        _ModeTemplate(
            rule_id="mode.decom.pack_ship_scope",
            domain_id="project",
            label="Pack / ship vs inventory",
            question=(
                "Confirm decommission scope — Visit-1 inventory vs Visit-2 derack/pack/ship — "
                "and which sites are racked vs pre-boxed."
            ),
            message="Decommission visit scope unset.",
            trigger=re.compile(r"(?i)\b(?:iron\s+mountain|de[\-\s]?rack|pack(?:ing)?|inventory)\b"),
            severity="blocker",
            score=0.94,
        ),
        _ModeTemplate(
            rule_id="mode.decom.packing_materials",
            domain_id="hardware",
            label="Packing materials ownership",
            question=(
                "Who furnishes packing materials / pallets — customer, Iron Mountain, or PurTera — "
                "and is pack-leave-onsite accepted?"
            ),
            message="Packing materials ownership unset.",
            trigger=re.compile(r"(?i)\b(?:packing\s+materials|pallet|shrink\s+wrap|box\s+shipping)\b"),
            severity="blocker",
            score=0.9,
        ),
        _ModeTemplate(
            rule_id="mode.decom.coi",
            domain_id="site",
            label="COI / union labor",
            question="Confirm COI / union-labor requirements per site before scheduling haul-out.",
            message="COI / union labor unset for decommission sites.",
            trigger=re.compile(r"(?i)\b(?:\bcoi\b|certificate of insurance|union\s+labor)\b"),
            severity="blocker",
            score=0.89,
        ),
        _ModeTemplate(
            rule_id="mode.decom.dock_hours",
            domain_id="site",
            label="Dock hours / truck size",
            question="Confirm dock hours, dock type, and max truck size for each pickup site.",
            message="Dock / truck constraints unset.",
            trigger=re.compile(r"(?i)\b(?:loading\s+dock|dock\s+hours|truck|elevator)\b"),
            severity="blocker",
            score=0.88,
        ),
        _ModeTemplate(
            rule_id="mode.decom.power_down",
            domain_id="project",
            label="Power-down ownership",
            question="Who owns equipment power-down / network take-down before pack-out — customer or PurTera?",
            message="Power-down ownership unset.",
            trigger=re.compile(r"(?i)\b(?:power\s+down|bring\s+down|de[\-\s]?energ|shutdown)\b"),
            severity="warning",
            score=0.87,
        ),
        _ModeTemplate(
            rule_id="mode.decom.inventory_list",
            domain_id="hardware",
            label="Pickup inventory authority",
            question="Confirm pickup/disposal inventory list is authoritative — any exclusions before crew arrives?",
            message="Pickup inventory list unset.",
            trigger=re.compile(r"(?i)\b(?:pickup|disposal|inventory|asset\s+tag|serial)\b"),
            severity="warning",
            score=0.86,
        ),
        _ModeTemplate(
            rule_id="mode.decom.carrier",
            domain_id="project",
            label="Carrier / Iron Mountain handoff",
            question="Who schedules Iron Mountain / carrier pickup — customer, Serviot, or PurTera?",
            message="Carrier scheduling ownership unset.",
            trigger=re.compile(r"(?i)\b(?:iron\s+mountain|carrier|freight|bol|bill of lading)\b"),
            severity="warning",
            score=0.85,
        ),
        _ModeTemplate(
            rule_id="mode.decom.bg_check",
            domain_id="site",
            label="Background check / dress code",
            question="Confirm background-check / dress-code requirements before scheduling onsite crew.",
            message="Background / dress-code requirements unset.",
            trigger=re.compile(r"(?i)\b(?:background|dress\s+code|badge|escort)\b"),
            severity="warning",
            score=0.84,
        ),
        _ModeTemplate(
            rule_id="mode.decom.visit_split",
            domain_id="project",
            label="Visit split billing",
            question="Confirm Visit-1 inventory vs Visit-2 pack/ship are separate mobilizations in this quote.",
            message="Visit split billing unset.",
            trigger=re.compile(r"(?i)\b(?:visit\s*1|visit\s*2|inventory|pack|de[\-\s]?rack)\b"),
            severity="warning",
            score=0.88,
        ),
        _ModeTemplate(
            rule_id="mode.decom.asset_tags",
            domain_id="hardware",
            label="Asset tag / serial capture",
            question="Must crew capture asset tags / serials at pickup — and into which customer system?",
            message="Asset tag capture unset.",
            trigger=re.compile(r"(?i)\b(?:asset\s+tag|serial|inventory|pickup)\b"),
            severity="warning",
            score=0.83,
        ),
        _ModeTemplate(
            rule_id="mode.decom.bol",
            domain_id="project",
            label="BOL / chain of custody",
            question="Who signs the BOL / chain-of-custody at pickup — customer site lead or PurTera?",
            message="BOL signer unset.",
            trigger=re.compile(r"(?i)\b(?:bol|bill of lading|chain of custody|iron\s+mountain|freight)\b"),
            severity="warning",
            score=0.82,
        ),
        _ModeTemplate(
            rule_id="mode.decom.hours",
            domain_id="site",
            label="Site hours / blackout",
            question="Confirm site operating hours / blackout windows for each pickup visit.",
            message="Pickup hours unset.",
            trigger=re.compile(r"(?i)\b(?:hours of operation|business hours|blackout|dock)\b"),
            severity="warning",
            score=0.81,
        ),
        _ModeTemplate(
            rule_id="mode.decom.tools",
            domain_id="hardware",
            label="Tools / lift at site",
            question="Confirm tools/lifts needed for derack — customer-furnished, or PurTera brings?",
            message="Derack tools/lift ownership unset.",
            trigger=re.compile(r"(?i)\b(?:lift|pallet\s+jack|tools?|derack|pack)\b"),
            severity="warning",
            score=0.8,
        ),
        _ModeTemplate(
            rule_id="mode.decom.labeling",
            domain_id="hardware",
            label="Box labeling standard",
            question="What box/pallet labeling standard is required before Iron Mountain accepts freight?",
            message="Labeling standard unset.",
            trigger=re.compile(r"(?i)\b(?:label|pallet|iron\s+mountain|box|shrink)\b"),
            severity="warning",
            score=0.79,
        ),
        _ModeTemplate(
            rule_id="mode.decom.waste",
            domain_id="project",
            label="Waste / e-waste",
            question="Is e-waste / scrap disposal in this quote, or customer-arranged after pack-out?",
            message="E-waste disposal ownership unset.",
            trigger=re.compile(r"(?i)\b(?:disposal|e[\-\s]?waste|scrap|recycle|pickup)\b"),
            severity="warning",
            score=0.78,
        ),
        _ModeTemplate(
            rule_id="mode.decom.escalation",
            domain_id="project",
            label="Onsite escalation",
            question="Who is the customer escalation contact if inventory differs from the pickup list onsite?",
            message="Onsite escalation contact unset.",
            trigger=re.compile(r"(?i)\b(?:inventory|pickup|escalat|contact|serviot)\b"),
            severity="warning",
            score=0.77,
        ),
        _ModeTemplate(
            rule_id="mode.decom.photos",
            domain_id="project",
            label="Before/after photos",
            question="Are before/after rack photos required for acceptance — and who archives them?",
            message="Photo acceptance requirement unset.",
            trigger=re.compile(r"(?i)\b(?:photo|picture|inventory|acceptance|pack)\b"),
            severity="warning",
            score=0.76,
        ),
        _ModeTemplate(
            rule_id="mode.decom.badge_lead",
            domain_id="site",
            label="Badge lead time",
            question="What badge / escort lead time is required before each pickup visit?",
            message="Badge lead time unset for decommission.",
            trigger=re.compile(r"(?i)\b(?:badge|escort|access|pickup|site|visit)\b"),
            severity="warning",
            score=0.75,
        ),
        _ModeTemplate(
            rule_id="mode.decom.weight_dims",
            domain_id="hardware",
            label="Crate weight / dims",
            question="Confirm max crate weight/dims Iron Mountain will accept — any oversize freight?",
            message="Crate weight/dims unset.",
            trigger=re.compile(r"(?i)\b(?:iron\s+mountain|pallet|freight|crate|pack|ship)\b"),
            severity="warning",
            score=0.74,
        ),
        _ModeTemplate(
            rule_id="mode.decom.data_wipe",
            domain_id="project",
            label="Data wipe ownership",
            question="Who owns data wipe / degauss before haul-out — customer, PurTera, or Iron Mountain?",
            message="Data wipe ownership unset.",
            trigger=re.compile(r"(?i)\b(?:wipe|degauss|sanitize|disposal|inventory|disk|drive)\b"),
            severity="warning",
            score=0.8,
        ),
        _ModeTemplate(
            rule_id="mode.decom.site_sequence",
            domain_id="project",
            label="Site pickup sequence",
            question="Confirm pickup sequence across sites — any hard date order or blackout sites?",
            message="Pickup site sequence unset.",
            trigger=re.compile(r"(?i)\b(?:site|pickup|sequence|schedule|visit|iron\s+mountain)\b"),
            severity="warning",
            score=0.78,
        ),
        _ModeTemplate(
            rule_id="mode.decom.rack_rails",
            domain_id="hardware",
            label="Rails / cages leave-behind",
            question="Do rail kits / cages stay in the rack after derack, or pack with the gear?",
            message="Rail/cage leave-behind unset.",
            trigger=re.compile(r"(?i)\b(?:rail|cage|derack|rack|pack|inventory)\b"),
            severity="warning",
            score=0.73,
        ),
        _ModeTemplate(
            rule_id="mode.decom.insurance",
            domain_id="commercial",
            label="In-transit insurance",
            question="Who carries in-transit insurance / declared value on Iron Mountain freight?",
            message="In-transit insurance ownership unset.",
            trigger=re.compile(r"(?i)\b(?:insurance|iron\s+mountain|freight|bol|ship|value)\b"),
            severity="warning",
            score=0.72,
        ),
        _ModeTemplate(
            rule_id="mode.decom.elevator",
            domain_id="site",
            label="Elevator / freight path",
            question="Confirm freight-elevator reservation and path from rack to dock for each pickup site.",
            message="Elevator / freight path unset.",
            trigger=re.compile(r"(?i)\b(?:elevator|dock|freight|pickup|haul|rack)\b"),
            severity="warning",
            score=0.74,
        ),
        _ModeTemplate(
            rule_id="mode.decom.manifest",
            domain_id="hardware",
            label="Pickup manifest format",
            question="What manifest format (CSV/portal) must crew complete at pickup — and who receives it?",
            message="Pickup manifest format unset.",
            trigger=re.compile(r"(?i)\b(?:manifest|inventory|asset\s+tag|serial|pickup|portal)\b"),
            severity="warning",
            score=0.73,
        ),
        _ModeTemplate(
            rule_id="mode.decom.seal",
            domain_id="project",
            label="Truck seal / custody",
            question="Are truck seals / custody photos required at departure — who holds seal numbers?",
            message="Truck seal / custody requirement unset.",
            trigger=re.compile(r"(?i)\b(?:seal|custody|bol|freight|iron\s+mountain|ship|pickup)\b"),
            severity="warning",
            score=0.72,
        ),
        _ModeTemplate(
            rule_id="mode.decom.floor_load",
            domain_id="site",
            label="Floor load / pallet jack",
            question="Confirm floor-load limits and pallet-jack access from rack row to dock.",
            message="Floor load / pallet-jack access unset.",
            trigger=re.compile(r"(?i)\b(?:pallet|jack|floor|dock|rack|haul|pack)\b"),
            severity="warning",
            score=0.71,
        ),
        _ModeTemplate(
            rule_id="mode.decom.customer_witness",
            domain_id="project",
            label="Customer witness",
            question="Must a customer witness be present for derack / seal — or is PurTera solo OK?",
            message="Customer witness requirement unset.",
            trigger=re.compile(r"(?i)\b(?:witness|escort|onsite|derack|pack|pickup|inventory)\b"),
            severity="warning",
            score=0.71,
        ),
        _ModeTemplate(
            rule_id="mode.decom.reuse_media",
            domain_id="hardware",
            label="Media / drive reuse",
            question="Do drives/media leave with chassis, or are they pulled and wiped separately before ship?",
            message="Drive/media disposition unset.",
            trigger=re.compile(r"(?i)\b(?:drive|disk|media|wipe|sanitize|inventory|disposal)\b"),
            severity="warning",
            score=0.7,
        ),
        _ModeTemplate(
            rule_id="mode.decom.quote_wave",
            domain_id="project",
            label="Sites in this quote",
            question="Confirm which pickup sites are in this quote wave — any deferrals before schedule?",
            message="Decom quote-wave site lock unset.",
            trigger=re.compile(r"(?i)\b(?:site|pickup|wave|schedule|visit|iron\s+mountain|inventory)\b"),
            severity="warning",
            score=0.7,
        ),
    ),
    MODE_ACCESS: (

        _ModeTemplate(
            rule_id="mode.access.reader_door_count",
            domain_id="access_control",
            label="Reader / door count",
            question="Confirm door/reader count and whether electrified hardware is OFE or PurTera-furnished.",
            message="Access-control door/reader scope unset.",
            trigger=re.compile(r"(?i)\b(?:card\s+reader|access\s+control|door|badge|electrified)\b"),
            severity="blocker",
            score=0.91,
        ),
    ),
    MODE_ASSESSMENT: (
        _ModeTemplate(
            rule_id="mode.assessment.roe",
            domain_id="project",
            label="Rules of engagement",
            question=(
                "Confirm rules of engagement: environments, time windows, allow-lists, "
                "and emergency stop contacts."
            ),
            message="Security assessment ROE unset.",
            trigger=re.compile(
                r"(?i)\b(?:penetrat|pentest|vulnerab|red\s+team|allow[\-\s]?list|rules?\s+of\s+engagement)\b"
            ),
            severity="blocker",
            score=0.93,
        ),
        _ModeTemplate(
            rule_id="mode.assessment.idp",
            domain_id="project",
            label="IdP / Entra sync",
            question=(
                "Azure AD / Entra ID tenant: Are user identities already synchronized to Azure AD, "
                "or is the directory still on-premises?"
            ),
            message="IdP sync state unset for cloud assessment / migration.",
            trigger=re.compile(r"(?i)\b(?:azure\s+ad|entra|conditional\s+access|mfa)\b"),
            severity="blocker",
            score=0.9,
        ),
        _ModeTemplate(
            rule_id="mode.assessment.report_pack",
            domain_id="project",
            label="Report deliverables",
            question=(
                "Which report deliverables are in the fixed fee "
                "(exec summary, full findings, retest)?"
            ),
            message="Assessment report pack unset.",
            trigger=re.compile(r"(?i)\b(?:executive\s+summary|assessment\s+report|findings|retest)\b"),
            severity="warning",
            score=0.86,
        ),
    ),
    MODE_AV: (
        _ModeTemplate(
            rule_id="mode.av_install.cable_conceal_drywall",
            domain_id="audio_visual",
            label="In-wall cable concealment pathway",
            question=(
                "Confirm pathway method for surface cable runs noted to move behind the wall: "
                "in-wall fish vs surface raceway."
            ),
            message=(
                "Behind-the-wall cable path is implied but pathway method is not locked."
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
            rule_id="mode.av_install.drywall_ownership",
            domain_id="audio_visual",
            label="Drywall cut / patch / paint ownership",
            question=(
                "If in-wall pathway is required, who owns drywall cut / patch / paint?"
            ),
            message=(
                "Drywall finish ownership is unset — no owner named and no SOW "
                "exclusion for drywall/patch/paint."
            ),
            trigger=re.compile(
                r"\b(?:behind\s+the\s+wall|in[\-\s]?wall|drywall|patch(?:ing)?\s*/?\s*paint)\b",
                re.I,
            ),
            answered_by=re.compile(
                r"\b(?:customer\s+owns\s+(?:drywall|patch|paint)|gc\s+owns\s+patch|"
                r"no\s+drywall|surface\s+raceway\s+only)\b",
                re.I,
            ),
            severity="warning",
            score=0.88,
        ),
        _ModeTemplate(
            rule_id="mode.av_install.keep_vs_remove_displays",
            domain_id="audio_visual",
            label="Existing displays keep vs remove",
            question=(
                "Confirm which existing TVs/displays stay mounted in place and which "
                "codecs / bars are removed vs reused."
            ),
            message=(
                "Keep/remove for existing AV gear is still open — no decisive "
                "stay + remove/keeper language in source."
            ),
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
                r"network\s+receptacle|cable(?:s)?\s+(?:run|across).{0,30}floor|"
                r"10\s+(?:ft|feet)|trip\s+hazard|poke[\-\s]?through)\b",
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
                "per photo annotations."
            ),
            message=(
                "Replication cable path is still open — source does not yet direct "
                "behind-wall / hide-the-run."
            ),
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
                "After ceiling-device decommission, who supplies matching ceiling tiles / patch?"
            ),
            message=(
                "Ceiling tile supply is still open — no customer/GC owner and no "
                "SOW exclusion for ceiling tiles."
            ),
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
        _ModeTemplate(
            rule_id="mode.av_install.ofe_displays",
            domain_id="audio_visual",
            label="OFE displays / mounts",
            question="Confirm TVs/mounts/cables are customer-furnished — any PurTera BOM lines?",
            message="AV OFE vs PurTera BOM unset.",
            trigger=re.compile(
                r"(?i)\b(?:procurement or supply of tvs?|owner[\-\s]?furnish|ofe|"
                r"customer[\-\s]?furnish|tvs?, mounts|display\s+mount|"
                r"audio[\-\s]?visual|conference\s+room|teams\s+room|hdmi|vesa|neat|yealink)\b"
            ),
            severity="blocker",
            score=0.91,
        ),
        _ModeTemplate(
            rule_id="mode.av_install.power_receptacle",
            domain_id="audio_visual",
            label="Display power receptacle",
            question="Confirm each display has a customer-provided live power receptacle within cord reach.",
            message="Display power readiness unset.",
            trigger=re.compile(
                r"(?i)\b(?:power\s+source|receptacle|outlet|connect each display|"
                r"audio[\-\s]?visual|conference\s+room|display|hdmi|vesa|mount)\b"
            ),
            severity="warning",
            score=0.86,
        ),
        _ModeTemplate(
            rule_id="mode.av_install.packaging_leave",
            domain_id="audio_visual",
            label="Removed gear / packaging",
            question="Confirm removed TVs/mounts/packaging stay with onsite IT — any haul-away in this quote?",
            message="Removed AV gear disposition unset.",
            trigger=re.compile(
                r"(?i)\b(?:packaging\s+materials|removed\s+tvs?|removed\s+mounts|leave all|"
                r"audio[\-\s]?visual|conference\s+room|teams\s+room|decom|swap)\b"
            ),
            severity="warning",
            score=0.85,
        ),
        _ModeTemplate(
            rule_id="mode.av_install.parking",
            domain_id="site",
            label="Tech parking",
            question="Confirm technician parking is available — are parking fees customer-reimbursed?",
            message="Parking / fee reimbursement unset.",
            trigger=re.compile(
                r"(?i)\b(?:onsite\s+parking|parking\s+fees?|audio[\-\s]?visual|"
                r"conference\s+room|onsite\s+install|technician)\b"
            ),
            severity="warning",
            score=0.82,
        ),
        _ModeTemplate(
            rule_id="mode.av_install.uc_platform",
            domain_id="audio_visual",
            label="UC platform lock",
            question="Confirm UC platform for room systems — Teams, Zoom, or dual-stack — before staging?",
            message="UC platform unset for room AV.",
            trigger=re.compile(
                r"(?i)\b(?:teams\s+room|zoom\s+room|neat|yealink|poly(?:com)?|"
                r"conference\s+room|audio[\-\s]?visual|room\s+bar)\b"
            ),
            severity="warning",
            score=0.84,
        ),
        _ModeTemplate(
            rule_id="mode.av_install.network_drop",
            domain_id="audio_visual",
            label="Room network drop",
            question="Confirm each room has a live data drop at the mount location — who owns any new pulls?",
            message="Room network drop readiness unset.",
            trigger=re.compile(
                r"(?i)\b(?:network|data\s+drop|poe|ethernet|hdmi|conference\s+room|"
                r"audio[\-\s]?visual|teams\s+room|mount)\b"
            ),
            severity="warning",
            score=0.83,
        ),
        _ModeTemplate(
            rule_id="mode.av_install.room_list",
            domain_id="audio_visual",
            label="Authoritative room list",
            question="Confirm the authoritative room / display list for this wave — any adds/drops before mobilize?",
            message="AV room list unset.",
            trigger=re.compile(
                r"(?i)\b(?:conference\s+room|huddle|teams\s+room|display|audio[\-\s]?visual|"
                r"room\s+list|site\s+count|install)\b"
            ),
            severity="warning",
            score=0.82,
        ),
        _ModeTemplate(
            rule_id="mode.av_install.test_call",
            domain_id="audio_visual",
            label="Acceptance test call",
            question="What pass/fail test call (Teams/Zoom) is required before site acceptance sign-off?",
            message="AV acceptance test unset.",
            trigger=re.compile(
                r"(?i)\b(?:acceptance|test\s+call|teams|zoom|audio[\-\s]?visual|"
                r"conference\s+room|sign[\-\s]?off)\b"
            ),
            severity="warning",
            score=0.81,
        ),
        _ModeTemplate(
            rule_id="mode.av_install.ladder_access",
            domain_id="site",
            label="Ladder / lift for mounts",
            question="Confirm 8ft ladder reaches all mounts — any scissor-lift or after-hours sites?",
            message="AV mount access method unset.",
            trigger=re.compile(
                r"(?i)\b(?:ladder|lift|ceiling|mount|vesa|audio[\-\s]?visual|"
                r"conference\s+room|install)\b"
            ),
            severity="warning",
            score=0.8,
        ),
        _ModeTemplate(
            rule_id="mode.av_install.spare_hardware",
            domain_id="hardware",
            label="Spare mounts / adapters",
            question="Are spare mounts/adapters staged for this wave — who holds RMA units during install?",
            message="AV spare hardware unset.",
            trigger=re.compile(
                r"(?i)\b(?:mount|adapter|hdmi|spare|rma|audio[\-\s]?visual|"
                r"conference\s+room|bom|hardware)\b"
            ),
            severity="warning",
            score=0.78,
        ),
        _ModeTemplate(
            rule_id="mode.av_install.cable_lengths",
            domain_id="audio_visual",
            label="Cable lengths / adapters",
            question="Confirm HDMI/USB/network cable lengths and adapters are OFE — any PurTera BOM lines?",
            message="AV cable length / adapter BOM unset.",
            trigger=re.compile(
                r"(?i)\b(?:hdmi|usb|adapter|cable|audio[\-\s]?visual|conference\s+room|mount)\b"
            ),
            severity="warning",
            score=0.77,
        ),
        _ModeTemplate(
            rule_id="mode.av_install.wall_type",
            domain_id="audio_visual",
            label="Wall / mount substrate",
            question="Confirm wall type (drywall/concrete/glass) at each mount — any blocking plates needed?",
            message="AV wall/mount substrate unset.",
            trigger=re.compile(
                r"(?i)\b(?:wall|mount|drywall|concrete|vesa|audio[\-\s]?visual|conference\s+room)\b"
            ),
            severity="warning",
            score=0.76,
        ),
        _ModeTemplate(
            rule_id="mode.av_install.escalation",
            domain_id="project",
            label="Day-of AV escalation",
            question="Who is the customer escalation contact if a room is blocked on install day?",
            message="AV day-of escalation unset.",
            trigger=re.compile(
                r"(?i)\b(?:escalat|contact|onsite|conference\s+room|audio[\-\s]?visual|install)\b"
            ),
            severity="warning",
            score=0.75,
        ),
        _ModeTemplate(
            rule_id="mode.av_install.wave_lock",
            domain_id="audio_visual",
            label="AV wave lock",
            question="Confirm which rooms/sites are in this AV wave — any adds/drops before mobilize?",
            message="AV wave / room lock unset.",
            trigger=re.compile(
                r"(?i)\b(?:room|wave|phase|site|audio[\-\s]?visual|conference|install)\b"
            ),
            severity="warning",
            score=0.75,
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
        _ModeTemplate(
            rule_id="mode.staff_aug.scope_boundary",
            domain_id="staff_augmentation",
            label="Staff-aug scope boundary",
            question="Confirm staff-aug scope: install-only, config-only, or install+config+documentation?",
            message="Staff-aug scope boundary unset.",
            trigger=re.compile(r"(?i)\b(?:staff\s+aug|installation and configuration|resource)\b"),
            severity="blocker",
            score=0.9,
        ),
        _ModeTemplate(
            rule_id="mode.staff_aug.supervision",
            domain_id="staff_augmentation",
            label="Supervision / acceptance",
            question="Who supervises staff-aug techs onsite and who signs daily/weekly acceptance?",
            message="Supervision/acceptance unset for staff aug.",
            trigger=re.compile(r"(?i)\b(?:staff\s+aug|technician|resource|onsite)\b"),
            severity="warning",
            score=0.84,
        ),
        _ModeTemplate(
            rule_id="mode.staff_aug.rate_card",
            domain_id="commercial",
            label="Rate card / overtime",
            question="Confirm bill rate card, overtime rules, and minimum hours per dispatch.",
            message="Staff-aug commercial rates unset.",
            trigger=re.compile(r"(?i)\b(?:rate|overtime|staff\s+aug|per\s+hour|T\s*&\s*M)\b"),
            severity="warning",
            score=0.83,
        ),
        _ModeTemplate(
            rule_id="mode.staff_aug.bridge",
            domain_id="staff_augmentation",
            label="Customer bridge / remote support",
            question="Who provides the customer bridge / remote support dial-in for each install window?",
            message="Customer bridge ownership unset.",
            trigger=re.compile(
                r"(?i)\b(?:bridge|remote\s+(?:tech|support)|dial[\-\s]?in|"
                r"idrac|troubleshoot|onsite|resource|poweredge)\b"
            ),
            severity="warning",
            score=0.86,
        ),
        _ModeTemplate(
            rule_id="mode.staff_aug.legacy_leave",
            domain_id="hardware",
            label="Legacy gear disposition",
            question="Confirm removed legacy gear stays onsite in a customer-designated area — any disposal?",
            message="Legacy gear disposition unset.",
            trigger=re.compile(
                r"(?i)\b(?:legacy\s+equipment|removed\s+legacy|designated\s+area|"
                r"parts?|swap|rma|failed|hardware|poweredge)\b"
            ),
            severity="warning",
            score=0.84,
        ),
        _ModeTemplate(
            rule_id="mode.staff_aug.docs",
            domain_id="project",
            label="Install documentation",
            question="Confirm install documentation / photos / completion report are in the fixed fee.",
            message="Install documentation deliverables unset.",
            trigger=re.compile(
                r"(?i)\b(?:installation\s+documentation|photographs|completion\s+report(?:ing)?|"
                r"status\s+update|findings|report|dispatch)\b"
            ),
            severity="warning",
            score=0.83,
        ),
        _ModeTemplate(
            rule_id="mode.staff_aug.no_imaging",
            domain_id="staff_augmentation",
            label="Imaging out of scope",
            question="Confirm imaging/configuration stays out of scope — physical install + cable only?",
            message="Imaging/config boundary unset.",
            trigger=re.compile(
                r"(?i)\b(?:no imaging|imaging or configuration|configuration performed|"
                r"troubleshoot|diagnos|component\s+level|hardware)\b"
            ),
            severity="warning",
            score=0.85,
        ),
        _ModeTemplate(
            rule_id="mode.staff_aug.parts_rma",
            domain_id="hardware",
            label="Parts / RMA",
            question="Who furnishes replacement parts / RMA — customer OEM contract, or PurTera?",
            message="Staff-aug parts / RMA ownership unset.",
            trigger=re.compile(
                r"(?i)\b(?:parts?|rma|oem|dell|poweredge|hardware|spare|inventory)\b"
            ),
            severity="warning",
            score=0.87,
        ),
        _ModeTemplate(
            rule_id="mode.staff_aug.skill_match",
            domain_id="staff_augmentation",
            label="Skill / OEM match",
            question="Confirm required OEM skill set (Dell/iDRAC, Cisco, etc.) for the local resource.",
            message="Staff-aug skill match unset.",
            trigger=re.compile(
                r"(?i)\b(?:local\s+resource|poweredge|dell|idrac|skill|technician|resource)\b"
            ),
            severity="warning",
            score=0.86,
        ),
        _ModeTemplate(
            rule_id="mode.staff_aug.travel_zone",
            domain_id="commercial",
            label="Travel / local only",
            question="Is this local-resource only (no travel), or are travel/expenses billable if needed?",
            message="Staff-aug travel zone unset.",
            trigger=re.compile(
                r"(?i)\b(?:local\s+resource|travel|per\s+day|dispatch|onsite|region)\b"
            ),
            severity="warning",
            score=0.84,
        ),
        _ModeTemplate(
            rule_id="mode.staff_aug.expand_gate",
            domain_id="commercial",
            label="Extra-day approval",
            question="Who approves additional days beyond the initial dispatch window before work continues?",
            message="Extra-day approval gate unset.",
            trigger=re.compile(
                r"(?i)\b(?:additional\s+days|approved before|dispatch window|per\s+day|change[\-\s]?order)\b"
            ),
            severity="warning",
            score=0.88,
        ),
    ),
    MODE_GENERIC: (
        _ModeTemplate(
            rule_id="mode.generic.day_rate",
            domain_id="commercial",
            label="Day-rate / overtime",
            question="Confirm day-rate vs T&M billing, overtime rules, and minimum hours per dispatch.",
            message="Day-rate / overtime commercial terms unset.",
            trigger=re.compile(
                r"(?i)\b(?:per\s+day|day[\-\s]?rate|billing\s+type|overtime|T\s*&\s*M|quote\s+me\s+by\s+the\s+day)\b"
            ),
            severity="blocker",
            score=0.9,
        ),
        _ModeTemplate(
            rule_id="mode.generic.scope_boundary",
            domain_id="project",
            label="Scope boundary",
            question="Confirm in-scope work stops at diagnosis vs parts swap vs full remediation — who approves expand?",
            message="Generic engagement scope boundary unset.",
            trigger=re.compile(
                r"(?i)\b(?:troubleshoot|diagnos|scope of work|hardware|remediat|dispatch)\b"
            ),
            severity="blocker",
            score=0.88,
        ),
        _ModeTemplate(
            rule_id="mode.generic.parts_ownership",
            domain_id="hardware",
            label="Parts / RMA ownership",
            question="Who furnishes replacement parts / RMA — customer OEM contract, or PurTera procurement?",
            message="Parts / RMA ownership unset.",
            trigger=re.compile(
                r"(?i)\b(?:parts?|rma|spare|oem|dell|poweredge|hardware|inventory)\b"
            ),
            severity="warning",
            score=0.86,
        ),
        _ModeTemplate(
            rule_id="mode.generic.onsite_poc",
            domain_id="site",
            label="Onsite POC",
            question="Who is the day-of onsite POC for escort, rack access, and escalation?",
            message="Onsite POC unset.",
            trigger=re.compile(
                r"(?i)\b(?:onsite|contact|escort|access|dispatch|technician|resource)\b"
            ),
            severity="warning",
            score=0.85,
        ),
        _ModeTemplate(
            rule_id="mode.generic.change_order",
            domain_id="commercial",
            label="Change-order gate",
            question="What triggers a change-order vs continuing under the approved day window?",
            message="Change-order gate unset.",
            trigger=re.compile(
                r"(?i)\b(?:additional\s+days|change[\-\s]?order|approved before|dispatch window)\b"
            ),
            severity="warning",
            score=0.84,
        ),
        _ModeTemplate(
            rule_id="mode.generic.remote_bridge",
            domain_id="project",
            label="Remote bridge",
            question="Who provides remote bridge / OEM support dial-in while the tech is onsite?",
            message="Remote bridge ownership unset.",
            trigger=re.compile(
                r"(?i)\b(?:remote|bridge|idrac|oem|support|troubleshoot|diagnos)\b"
            ),
            severity="warning",
            score=0.83,
        ),
        _ModeTemplate(
            rule_id="mode.generic.acceptance",
            domain_id="project",
            label="Acceptance criteria",
            question="What is the pass/fail acceptance for this dispatch — and who signs off?",
            message="Dispatch acceptance criteria unset.",
            trigger=re.compile(
                r"(?i)\b(?:acceptance|sign[\-\s]?off|status\s+update|troubleshoot|dispatch)\b"
            ),
            severity="warning",
            score=0.82,
        ),
        _ModeTemplate(
            rule_id="mode.generic.tools_access",
            domain_id="hardware",
            label="Tools / console access",
            question="Confirm console/iDRAC/IPMI credentials and any special tools the tech must bring.",
            message="Console / tools access unset.",
            trigger=re.compile(
                r"(?i)\b(?:idrac|ipmi|console|credential|diagnostic|poweredge|dell)\b"
            ),
            severity="warning",
            score=0.81,
        ),
        _ModeTemplate(
            rule_id="mode.generic.hours",
            domain_id="site",
            label="Site hours",
            question="Confirm site operating hours / blackout windows for this dispatch.",
            message="Dispatch site hours unset.",
            trigger=re.compile(
                r"(?i)\b(?:hours|blackout|business\s+hours|after[\-\s]?hours|dispatch|onsite)\b"
            ),
            severity="warning",
            score=0.8,
        ),
        _ModeTemplate(
            rule_id="mode.generic.report_pack",
            domain_id="project",
            label="Report deliverables",
            question="Which report deliverables are in the fixed fee (findings, next steps, photos)?",
            message="Dispatch report pack unset.",
            trigger=re.compile(
                r"(?i)\b(?:report|status\s+update|findings|documentation|completion)\b"
            ),
            severity="warning",
            score=0.79,
        ),
        _ModeTemplate(
            rule_id="mode.generic.safety",
            domain_id="site",
            label="Site safety / escort",
            question="Confirm badge/escort/safety briefing requirements before the tech arrives.",
            message="Site safety / escort unset.",
            trigger=re.compile(
                r"(?i)\b(?:badge|escort|safety|access|onsite|facility)\b"
            ),
            severity="warning",
            score=0.78,
        ),
        _ModeTemplate(
            rule_id="mode.generic.spare_hold",
            domain_id="hardware",
            label="Failed-parts hold",
            question="Where do failed parts stay after swap — customer cage, ship-back, or PurTera holds?",
            message="Failed-parts hold location unset.",
            trigger=re.compile(
                r"(?i)\b(?:parts?|swap|rma|failed|hardware|poweredge|inventory)\b"
            ),
            severity="warning",
            score=0.77,
        ),
    ),
}


def _ground_template_question(tmpl: _ModeTemplate, blob: str) -> str:
    """Specialize template wording with evidence anchors (city / lean site / OEM)."""
    from orbitbrief_core.pm_handoff.pm_ask_rewrite import (
        extract_site_names,
        inject_site_anchor,
    )

    q = tmpl.question
    sites = extract_site_names(blob or "")
    # Pin cross-deal mode stems to site + OEM flavor.
    if tmpl.rule_id.startswith(
        (
            "mode.av_install.",
            "mode.wireless",
            "mode.decom.",
            "mode.staff_aug.",
            "mode.generic.",
        )
    ):
        q = inject_site_anchor(q, sites, blob=blob or "")
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
        # Annotations / SOW exclusions already settle many AV "Confirm…" asks.
        if source_material_answers(tmpl.rule_id, blob or ""):
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
        # A mode ask must cite a real atom, like every other generator. This is
        # the invariant question_generators.py opens by declaring — "no template
        # fires without a matching atom/snippet" — and mode templates were the
        # one place exempt from it.
        #
        # The exemption is what makes a brief read as "this deal is wireless,
        # here are the wireless questions" instead of questions about THIS deal:
        # the pack label alone could fire an ask the documents never support.
        # Clayton was asked for an AP count, an RF channel plan and a wireless
        # design owner on a 437-store technician dispatch job.
        #
        # Measured on Clayton (1907 atoms), templates surviving per mode:
        #   wireless_install 17 -> 10   av_install 11 -> 7   decom 21 -> 15
        #   staff_aug 12 -> 12          generic   11 -> 11
        # The modes the exemption claimed to protect (checklist-evidence ones)
        # lose nothing — their templates were already grounded. What it actually
        # protected were weakly-supported asks in wireless / AV / decom.
        #
        # Type still shapes the questioning: _MODE_TEMPLATES decides WHICH
        # families are worth asking. Evidence decides whether each one is a real
        # gap in THIS deal.
        grounded = _with_evidence(
            cand,
            atoms=atom_list,
            trigger=tmpl.trigger,
            docs_by_id=docs_by_id,
            require=True,
        )
        if grounded is None:
            continue
        # Soft modes: if no atom citation, attach a blob-snippet source so quality
        # gates still see evidence (trigger already matched the deal blob).
        if not grounded.evidence_sources:
            snip = (blob or "")[:180].strip()
            if len(snip) >= 24:
                grounded = QuestionCandidate(
                    rule_id=grounded.rule_id,
                    domain_id=grounded.domain_id,
                    label=grounded.label,
                    severity=grounded.severity,
                    message=grounded.message,
                    suggested_open_question=grounded.suggested_open_question,
                    observed_summary=grounded.observed_summary,
                    source=grounded.source,
                    score=grounded.score,
                    evidence_atom_ids=list(grounded.evidence_atom_ids),
                    evidence_sources=[
                        {
                            "filename": "deal-evidence",
                            "snippet": snip,
                            "locator": "blob",
                        }
                    ],
                    project_mode=grounded.project_mode,
                )
            else:
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


_KEEP_DISPLAY_DECISION_RE = re.compile(
    r"\b(?:tvs?\s+to\s+stay|stay\s+in\s+place|"
    r"remain\s+(?:on\s+(?:existing\s+)?(?:vesa|floor|mount)|in\s+(?:their\s+)?(?:current\s+)?position))\b",
    re.I,
)
_REMOVE_OR_KEEPER_DECISION_RE = re.compile(
    r"\b(?:(?:will|to)\s+be\s+removed|almost\s+all.{0,60}removed|"
    r"except\s+(?:for\s+)?(?:the\s+)?hdmi|"
    r"hdmi\s+(?:over\s+ethernet|replicator).{0,60}(?:stay|retained|keep|exception))\b",
    re.I,
)
_REPLICATION_PATH_DECISION_RE = re.compile(
    r"\b(?:replication\s+cable).{0,140}(?:behind\s+(?:the\s+)?wall|not\s+be\s+visible|should\s+be\s+moved)|"
    r"(?:should\s+be\s+moved|noted\s+for\s+repositioning|rerout(?:e|ing)|moved).{0,60}behind\s+(?:the\s+)?wall\b",
    re.I,
)
_OOS_SECTION_RE = re.compile(
    r"\b(?:out\s+of\s+scope|excluded\s+unless|services\s+are\s+excluded)\b",
    re.I,
)
_DRYWALL_FINISH_ITEM_RE = re.compile(
    r"\b(?:drywall\s+repair|painting|patching|finish\s+work)\b",
    re.I,
)
_CEILING_TILE_ITEM_RE = re.compile(
    r"\b(?:ceiling\s+grid\s+repair|replacement\s+ceiling\s+tiles?|ceiling\s+tiles?)\b",
    re.I,
)
_CEILING_TILE_CUSTOMER_PROVIDES_RE = re.compile(
    r"\b(?:provide\s+replacement\s+ceiling\s+tiles?|customer\s+owns\s+tiles?|"
    r"tile\s+match\s+not\s+required|gc\s+owns\s+ceiling\s+repair)\b",
    re.I,
)


def source_material_answers(rule_id: str, blob: str) -> bool:
    """True when deal source already settles this ask — do not re-ask as Confirm.

    Survey annotations and SOW exclusions are answers. Only leave asks that are
    still open decisions (method choices, true open_questions in the kit).
    """
    b = blob or ""
    rid = (rule_id or "").lower()
    if rid.endswith("keep_vs_remove_displays") or rid.endswith("keep_vs_remove"):
        return bool(_KEEP_DISPLAY_DECISION_RE.search(b) and _REMOVE_OR_KEEPER_DECISION_RE.search(b))
    if rid.endswith("replication_cable_path"):
        return bool(_REPLICATION_PATH_DECISION_RE.search(b))
    if rid.endswith("drywall_ownership"):
        oos_finish = bool(_OOS_SECTION_RE.search(b) and _DRYWALL_FINISH_ITEM_RE.search(b))
        return bool(
            oos_finish
            or re.search(
                r"\b(?:customer\s+owns\s+(?:drywall|patch|paint)|gc\s+owns\s+patch|"
                r"no\s+drywall|surface\s+raceway\s+only)\b",
                b,
                re.I,
            )
        )
    if rid.endswith("ceiling_tile_match"):
        oos_tiles = bool(_OOS_SECTION_RE.search(b) and _CEILING_TILE_ITEM_RE.search(b))
        return bool(oos_tiles or _CEILING_TILE_CUSTOMER_PROVIDES_RE.search(b))
    return False


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
        if source_material_answers(c.rule_id, blob):
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
    # Prefer curated mode templates over raw evidence dumps when they collide
    # (e.g. "RISKS: Replication cable…" vs mode.av_install.replication_cable_path).
    source_rank = {"pm_gold": 4, "mode_template": 3, "evidence": 2, "yaml_safety": 1}.get(
        c.source, 0
    )
    evidence_rank = 1 if c.evidence_sources else 0
    # PM-gold teaching rows must win their semantic cluster even without
    # citations yet (hash embedders falsely merge demarc vs survey asks).
    gold_boost = 1 if c.source == "pm_gold" else 0
    # Deal-locked mode/photo/instruction asks outrank generic pmcover.*
    rid = c.rule_id or ""
    specificity = 0
    if rid.startswith("mode."):
        specificity = 3
    elif rid.startswith(("photo.", "instruction.", "qty.", "decision.")):
        specificity = 2
    elif rid.startswith("pmcover."):
        specificity = 0
    else:
        specificity = 1
    return (
        gold_boost,
        -SEVERITY_SORT.get(c.severity, 9),
        specificity,
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
        from orbitbrief_core.pm_handoff.pm_ask_rewrite import family_key_for_question

        source_order = {
            "pm_gold": 0,
            "mode_template": 1,
            "evidence": 2,
            "yaml_safety": 3,
        }.get(c.source, 4)
        rid = c.rule_id or ""
        qtext = c.suggested_open_question or c.message or ""
        fam = family_key_for_question(qtext, rid) or ""
        # Prefer deal-specific families ahead of generic coverage / commercial stems.
        fam_penalty = 1 if rid.startswith("pmcover.") else 0
        if fam in {
            "travel",
            "schedule",
            "hours",
            "budget",
            "furnish",
            "payment",
            "engineer_name",
            "ceiling",
            "pathway_own",
            "acceptance",
            "survey",
            "ap_list",
            "sites",
            "cable_vs_swap",
            "av_keep",
            "pathway",
            "lift_access",
            "net_remediation",
            "cat6_plenum",
            "tm_rounding",
            "escort_badge",
            "backboards",
            "cabling_tm",
        }:
            fam_penalty += 2
        from orbitbrief_core.pm_handoff.pm_ask_rewrite import is_hq_only_generic

        hq_penalty = 3 if is_hq_only_generic(qtext) else 0
        mode_bonus = 0 if rid.startswith("mode.") else 1
        # Prefer asks that already carry a site / OEM / model lock.
        locked = (" — at " in qtext) or bool(
            re.search(
                r"(?i)\b(?:TV1|Meraki|Cisco|Azure|Entra|SSID|OEM|RFP|"
                r"raceway|home\s*runs?|1-for-1|PowerEdge|Tilly|Dollar\s+Tree|"
                r"GRUBBRR|Iron\s+Mountain|Serviot)\b",
                qtext,
            )
        )
        lock_bonus = 0 if locked else 1
        return (
            SEVERITY_SORT.get(c.severity, 9),
            mode_bonus,
            fam_penalty + hq_penalty,
            lock_bonus,
            -c.score,
            source_order,
            qtext,
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
    # Mode templates are intentionally distinct PM decisions — never let embedding
    # paraphrase clustering drop a unique mode.* rule_id (starved A++++++ pools).
    mode_kept = {c.rule_id for c in deduped if (c.rule_id or "").startswith("mode.")}
    for c in uniq:
        rid = c.rule_id or ""
        if rid.startswith("mode.") and rid not in mode_kept:
            deduped.append(c)
            mode_kept.add(rid)
    ranked = sorted(deduped, key=sort_key)
    # Neural MMR: greedily keep high-score asks that stay diverse (≥0.70 apart).
    selected = _neural_mmr_select(ranked, cap=max(1, cap))
    meta = {
        "semantic_dedupe_input": cluster_meta.input_count,
        "semantic_dedupe_output": cluster_meta.output_count,
        "semantic_dedupe_merged_pairs": cluster_meta.merged_pairs,
        "semantic_dedupe_embedder": cluster_meta.embedder_model,
        # Loud, structural, and in the artifact: a brief built on hash
        # vectors must SAY so. Silent degradation is why the embedder
        # was found down only by going and looking.
        "embedder_health": _embedder_health(),
        "semantic_dedupe_cosine_threshold": cluster_meta.cosine_threshold,
        "mmr_selected": len(selected),
        **relevance_meta,
    }
    return selected, meta


def _neural_mmr_select(
    ranked: list[QuestionCandidate],
    *,
    cap: int,
    # Tighter than 0.70 — paraphrase near-dups were still landing side-by-side.
    diversity_cosine: float = 0.62,
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
    # Always seat distinct mode templates first — they are intentionally different
    # decisions even when embeddings look similar (pack/ship vs dock vs BOL).
    for i, c in enumerate(ranked):
        if len(picked) >= cap:
            break
        if (c.rule_id or "").startswith("mode."):
            picked.append(i)
    for i, _c in enumerate(ranked):
        if len(picked) >= cap:
            break
        if i in picked:
            continue
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


def select_shortlist(pool_cards: list[GapCard], *, cap: int) -> list[GapCard]:
    """Cut the capped PM Review Queue shortlist out of the full question pool.

    One ask per family, no unflavored coverage stems (cross-deal clones), and
    ordered by the question-quality head.

    Ordering was measured on held-out deals (top-12 good rate, 5 deal splits):

        pool order (was shipped)   36.6%
        severity first             32.1%
        quality head               47.5%

    Severity is deliberately NOT the sort key. It reads like the right one, but
    a DeepSeek audit found 87% of cards labelled ``blocker`` were not worth
    asking — so leading with severity promotes junk, and measured *worse* than
    doing nothing. When the head is unavailable the pool order is kept, since
    that beats severity ordering too.
    """
    from orbitbrief_core.pm_handoff.pm_ask_rewrite import (
        family_key_for_question,
        is_unflavored_coverage,
        normalize_pm_ask,
    )
    from orbitbrief_core.pm_handoff.question_quality_head import load_model, score_card

    short_families: set[str] = set()
    cards: list[GapCard] = []
    model = load_model()
    if model:
        def _sort_key(item):
            score, index, card = item
            # A pm_gold ask is a PM telling us to ask this. That outranks a head
            # trained on an LLM's opinion — without this, teaching a question
            # only to have the ranker bury it makes the correction loop a lie.
            return (
                not (card.rule_id or "").startswith("pm_gold"),
                score is None,
                -(score or 0.0),
                index,
            )

        scored = [(score_card(c, model), i, c) for i, c in enumerate(pool_cards)]
        # Unscorable cards keep their pool position rather than sinking.
        ordered_pool = [c for _s, _i, c in sorted(scored, key=_sort_key)]
    else:
        ordered_pool = list(pool_cards)
    for card in ordered_pool:
        if len(cards) >= max(1, int(cap)):
            break
        qtext = normalize_pm_ask(card.suggested_open_question or card.message or "")
        if is_unflavored_coverage(qtext):
            continue
        fam = family_key_for_question(qtext, card.rule_id)
        if fam and fam in short_families:
            continue
        if fam:
            short_families.add(fam)
        cards.append(card)
    return cards


# Slots on the handoff guaranteed to deal-specific exposure asks. 0 disables.
EXPOSURE_RESERVED_SLOTS = int(
    __import__("os").environ.get("ORBITBRIEF_EXPOSURE_RESERVED_SLOTS", "3")
)


def _is_exposure(card: Any) -> bool:
    return str(getattr(card, "rule_id", "") or "").startswith("llm.exposure.")


def _reserve_exposure_slots(
    cards: list[Any],
    pool_cards: list[Any],
    *,
    cap: int,
    reserve: int = EXPOSURE_RESERVED_SLOTS,
) -> list[Any]:
    """Guarantee a few PM slots to deal-specific exposure asks.

    Coverage templates and exposure asks are not competing on one axis, but the
    shortlist ranks them as if they were, and templates win. Measured across
    three modes 2026-08-13, all with 8 generated candidates and 7-8 admitted to
    the pool:

        av_install        pool 50 (at cap)  ->  0 published
        wireless_install  pool 32           ->  1 published
        staff_aug         pool 44           ->  3 published

    The av_install brief dropped, among others, "the SOW references 3 primary
    room installations, but the deal mentions 4 conference rooms -- which count
    is correct?" -- a contradiction between two documents in the deal -- and an
    unconfirmed union-labour surcharge. Its twelve published asks were all
    generic coverage (pathway ownership, badging, wall type) that a PM could ask
    from memory on any AV job. Losing a document contradiction to "what wall
    type is it" is the ranking making the wrong trade.

    So reserve, rather than re-score: exposure asks take at most `reserve` of the
    cap, displacing the LOWEST-ranked non-exposure cards. Nothing is invented --
    only pool cards that already passed grounding, quality and dedupe are
    eligible, and if the generator produced none this is a no-op.
    """
    if reserve <= 0 or not cards or not pool_cards:
        return cards
    have = sum(1 for c in cards if _is_exposure(c))
    want = min(reserve, max(0, int(cap))) - have
    if want <= 0:
        return cards
    chosen = {id(c) for c in cards}
    # pool_cards is in rank order, so this takes the best unpublished exposure asks.
    extra = [c for c in pool_cards if _is_exposure(c) and id(c) not in chosen][:want]
    if not extra:
        return cards
    keep = [c for c in cards if _is_exposure(c)]
    others = [c for c in cards if not _is_exposure(c)]
    # Drop from the tail: the lowest-ranked coverage asks.
    others = others[: max(0, len(others) - len(extra))]
    merged = keep + extra + others
    # Preserve the original ordering for everything that survived.
    order = {id(c): i for i, c in enumerate(cards)}
    merged.sort(key=lambda c: order.get(id(c), 10_000))
    return merged[: max(1, int(cap))]


def _routing_provenance(routing: Any) -> dict[str, Any]:
    """Which rung of the router decided, and did the head agree.

    `source` is the useful field. "llm_scope_router" means the LLM rung decided;
    "service_router_head" means the parser's head answer was passed through
    untouched. The head measured 0.529 held-out and answered `wireless` on six
    consecutive sampled deals, so knowing WHICH produced a mode is the difference
    between trusting the questions and re-deriving them by hand.

    Absent routing is reported as `{"decided": False}` rather than omitted — a
    missing key reads as a bug, and "no opinion" is a real, deliberate answer
    that leaves the keyword cascade in charge.
    """
    if not isinstance(routing, Mapping) or not routing:
        return {"decided": False}
    out: dict[str, Any] = {"decided": True}
    for key in ("primary", "source", "confidence", "abstained", "abstain_reason"):
        val = routing.get(key)
        if val not in (None, "", []):
            out[key] = val
    # Scope summary itself is large; its hash is enough to tell two runs apart.
    sha = routing.get("scope_summary_sha256")
    if sha:
        out["scope_summary_sha256"] = sha
    return out


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
    pool_cap: int = DEFAULT_QUESTION_POOL_CAP,
) -> tuple[list[GapCard], dict[str, Any]]:
    """Build the curated customer_questions shortlist + evidence pool meta.

    Returns ``(shortlist, meta)``. ``meta["pool"]`` holds up to ``pool_cap``
    evidence-grounded cards for audit / SowSmith — the PM Review Queue only
    renders the shortlist (``cap``, default 8).
    """
    atoms = _atoms_from_sources(envelope, report)
    header_blob = _deal_header_blob(envelope if isinstance(envelope, Mapping) else None)
    atom_blob = _blob_from_atoms(atoms)
    blob = f"{header_blob}\n{atom_blob}".strip() if header_blob else atom_blob
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
    # Evidence-derived generators (sites / photos / qty / decisions) fill the pool.
    from orbitbrief_core.pm_handoff.question_generators import build_extended_candidates

    candidates.extend(
        build_extended_candidates(
            sites=list(sites),
            atoms=atoms,
            project_mode=project_mode,
            blob=blob,
            envelope=envelope if isinstance(envelope, Mapping) else None,
            docs_by_id=docs_by_id,
        )
    )
    # Deal-specific exposure, written by a model that reads the atoms and the
    # questions already being asked. Templates cannot ask what nobody wrote down
    # in advance -- reviewed 2026-08-13, they covered technical execution well
    # and never asked who eats an aborted visit on a 437-site T&M dispatch, or
    # for a building COI on a Manhattan display install. Additive: these join
    # the same pool and the same ranker, and every one must cite a real atom id
    # or it is dropped inside the generator.
    # Report this in the METRICS, not just the log. question_llm and
    # scope_router both log at INFO, and production only emits the worker's own
    # logger — so after the first live run I could not tell whether the
    # generator had run and produced nothing, or never run at all. A stage that
    # can silently contribute zero has to say so somewhere the artifact keeps.
    _llm_status = "unwired"
    _llm_count = 0
    _llm_diag: dict[str, Any] = {}
    _llm_rule_ids: list[str] = []
    try:
        from orbitbrief_core.pm_handoff.question_llm import candidates_from_llm
        # RAW client: question_llm speaks the inference protocol
        # (messages, model=), not pm_briefing's (system=, user=).
        from orbitbrief_core.pm_handoff.builder import _raw_chat

        _chat, _model = _raw_chat()
        if _chat is not None and _model:
            _llm_status = "ran"
            _llm_new = list(
                candidates_from_llm(
                    atoms=atoms,
                    project_mode=project_mode,
                    existing_questions=[
                        getattr(c, "suggested_open_question", "") for c in candidates
                    ],
                    chat=_chat,
                    model=_model,
                    deal_label=str((envelope or {}).get("project_id") or "")
                    if isinstance(envelope, Mapping)
                    else "",
                    diagnostics=_llm_diag,
                    case_dir=case_dir,
                )
            )
            _llm_count = len(_llm_new)
            _llm_rule_ids = [str(c.rule_id) for c in _llm_new]
            candidates.extend(_llm_new)
    except Exception as exc:  # never let the extra questions break the brief
        import logging as _logging

        _llm_status = f"error:{type(exc).__name__}"
        _logging.getLogger(__name__).warning("question_llm: skipped (%s)", exc)

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
    # Non-gold asks MUST cite evidence — no more "Mode template for X" with empty sources.
    grounded_all: list[QuestionCandidate] = []
    for c in candidates:
        require = c.source != "pm_gold"
        g = _with_evidence(c, atoms=atoms, docs_by_id=docs_by_id, require=require)
        if g is not None and (g.evidence_sources or g.source == "pm_gold"):
            grounded_all.append(g)
    candidates = grounded_all

    pool_limit = max(int(cap), int(pool_cap))
    ranked, dedupe_meta = rank_and_cap(candidates, cap=pool_limit, evidence_blob=blob)
    pre_filter = len(ranked)
    # Final containment: never ship smalltalk / meta even if an atom slipped
    # past type gates (e.g. mis-typed open_question).
    ranked = [
        c
        for c in ranked
        if _is_customer_facing_question(c.suggested_open_question or c.message or "")
    ]
    after_facing = len(ranked)
    # Triple-check: drop any ask that still has zero matching sources
    # (except rare PM-gold teaching rows).
    ranked = [
        c
        for c in ranked
        if c.evidence_sources or c.source == "pm_gold"
    ]
    after_cite = len(ranked)
    # If filters ate the pool, top-up from grounded candidates that still pass
    # quality gates (dedupe already ran — prefer unused rule_ids).
    if len(ranked) < int(pool_cap):
        have = {c.rule_id for c in ranked}
        extras: list[QuestionCandidate] = []
        for c in sorted(candidates, key=_candidate_rank_tuple, reverse=True):
            if c.rule_id in have:
                continue
            q = c.suggested_open_question or c.message or ""
            if not _is_customer_facing_question(q):
                continue
            if not (c.evidence_sources or c.source == "pm_gold"):
                continue
            extras.append(c)
            have.add(c.rule_id)
            if len(ranked) + len(extras) >= int(pool_cap):
                break
        ranked = ranked + extras
    from orbitbrief_core.pm_handoff.pm_ask_rewrite import (
        family_key_for_question,
        is_unflavored_coverage,
        normalize_pm_ask,
    )
    from orbitbrief_core.pm_handoff.question_quality import (
        filter_perfect_questions,
        pool_scorecard,
        validate_question_card,
    )

    # One ask per commercial/coverage family across the whole pool (kills near-dups).
    _SINGLETON_FAMILIES = frozenset(
        {
            "payment",
            "travel",
            "schedule",
            "hours",
            "budget",
            "furnish",
            "cable_vs_swap",
            "engineer_name",
            "survey",
            "pathway",
            "pathway_own",
            "acceptance",
            "ap_list",
            "lift_access",
            "net_remediation",
            "cat6_plenum",
            "tm_rounding",
            "escort_badge",
            "backboards",
            "cabling_tm",
            "milestones",
            "single_poc",
            "wifi_creds",
            "qty_imac",
            "sites",
            "ceiling",
            "av_keep",
            "install_docs",
            "site_access_gap",
            "site_onsite",
            "site_cutover",
            "site_accept",
            "site_ceiling",
            "site_wifi",
            "site_parking",
            "site_dock",
        }
    )

    have_texts: set[str] = set()

    # Why each generated question did or did not reach the PM. The exposure
    # generator emitted 8 candidates on Clayton and published 2, then 1; the
    # other 6-7 left no trace anywhere in the artifact, so there was no way to
    # tell a quality drop from a family collapse from an out-rank without
    # guessing. Guessing cost a full deploy cycle on the last bug, so measure
    # instead: every admission decision records itself here.
    _llm_fate: dict[str, str] = {}

    def _note_fate(rule_id: str, why: str) -> None:
        if str(rule_id or "").startswith("llm."):
            _llm_fate.setdefault(str(rule_id), why)

    def _norm_q(text: str) -> str:
        return re.sub(r"\W+", " ", (text or "").lower()).strip()

    def _accept_card(
        card: GapCard,
        *,
        have_ids: set[str],
        have_families: set[str],
        family_limit: bool,
    ) -> GapCard | None:
        if card.rule_id in have_ids:
            _note_fate(card.rule_id, "duplicate_rule_id")
            return None
        qtext = normalize_pm_ask(card.suggested_open_question or card.message or "")
        if not qtext:
            _note_fate(card.rule_id, "empty_after_normalize")
            return None
        from dataclasses import replace

        card = replace(card, suggested_open_question=qtext)
        nq = _norm_q(qtext)
        if nq and nq in have_texts:
            _note_fate(card.rule_id, "duplicate_text")
            return None
        viols = validate_question_card(card)
        if viols:
            quality_dropped.extend(viols)
            _note_fate(card.rule_id, "quality:" + ",".join(sorted({v.code for v in viols})))
            return None
        fam = family_key_for_question(qtext, card.rule_id)
        if fam and fam in have_families and (family_limit or fam in _SINGLETON_FAMILIES):
            _note_fate(card.rule_id, f"family_collapse:{fam}")
            return None
        have_ids.add(card.rule_id)
        if nq:
            have_texts.add(nq)
        if fam:
            have_families.add(fam)
        _note_fate(card.rule_id, "admitted_to_pool")
        return card

    # Quality-aware fill: keep pulling ranked candidates until perfect pool hits cap.
    # Family dedupe: at most one ask per decision family in the pool head.
    pool_cards: list[GapCard] = []
    quality_dropped: list = []
    have_perfect: set[str] = set()
    have_families: set[str] = set()
    for c in ranked:
        if len(pool_cards) >= max(1, int(pool_cap)):
            break
        card = c.to_gap_card()
        # Family limit for first 16 (shortlist neighborhood); relax later to fill pool.
        fam_limit = len(pool_cards) < max(16, int(cap) * 2)
        kept = _accept_card(
            card, have_ids=have_perfect, have_families=have_families, family_limit=fam_limit
        )
        if kept is not None:
            pool_cards.append(kept)
    # If still short, scan remaining grounded candidates (pre-rank leftovers).
    if len(pool_cards) < int(pool_cap):
        for c in sorted(candidates, key=_candidate_rank_tuple, reverse=True):
            if len(pool_cards) >= int(pool_cap):
                break
            q = c.suggested_open_question or c.message or ""
            if not _is_customer_facing_question(q):
                continue
            if not (c.evidence_sources or c.source == "pm_gold"):
                continue
            card = c.to_gap_card()
            fam_limit = len(pool_cards) < max(16, int(cap) * 2)
            kept = _accept_card(
                card,
                have_ids=have_perfect,
                have_families=have_families,
                family_limit=fam_limit,
            )
            if kept is not None:
                pool_cards.append(kept)
    cards = select_shortlist(pool_cards, cap=cap)
    cards = _reserve_exposure_slots(cards, pool_cards, cap=cap)
    if not cards:
        shortlist_cards, _ = filter_perfect_questions(
            [c.to_gap_card() for c in ranked[: max(1, int(cap))]]
        )
        cards = shortlist_cards
    quality = pool_scorecard(pool_cards)
    meta = {
        "project_mode": project_mode,
        # WHY this mode. service_routing.primary decides project_mode, which
        # decides which questions the PM is asked — and none of it appeared in
        # the artifact, so an audit could see the answer and not the reasoning.
        # That cost a wrong diagnosis: routing was read as broken ("absent on
        # every deal") when it was working and correctly overriding a bad head.
        # The head answered `wireless` for a staff-augmentation deal; the LLM
        # rung said `staff_augmentation` and won. Only the banked training rows
        # showed it. A decision this load-bearing has to be legible where the
        # questions are.
        "service_routing": _routing_provenance(service_routing),
        "candidate_count_before_cap": len(candidates),
        # "unwired" (no chat model) | "ran" | "error:<Type>" — plus how many it
        # contributed. Without this a zero-contribution stage is invisible.
        "llm_exposure": {
            "status": _llm_status,
            "candidates": _llm_count,
            **_llm_diag,
            # generated -> published, with the reason for every one that fell out.
            # "not_admitted" is the default and means it never reached the pool
            # admission check at all: cut by suppress_answered / apply_feedback,
            # or out-ranked before the pool filled. That is a different problem
            # from a quality drop or a family collapse, and the distinction is
            # the whole point of measuring.
            "fate": {
                **{rid: "not_admitted" for rid in _llm_rule_ids},
                **_llm_fate,
            },
            "published": sorted(
                r.rule_id for r in cards if str(r.rule_id or "").startswith("llm.")
            ),
        },
        "sources": {
            "evidence": sum(1 for c in ranked[: len(cards)] if c.source == "evidence"),
            "mode_template": sum(
                1 for c in ranked[: len(cards)] if c.source == "mode_template"
            ),
            "yaml_safety": sum(1 for c in ranked[: len(cards)] if c.source == "yaml_safety"),
            "pm_gold": sum(1 for c in ranked[: len(cards)] if c.source == "pm_gold"),
        },
        "with_citations": sum(1 for c in cards if c.sources),
        "cap": cap,
        "pool_cap": pool_cap,
        "pool_size": len(pool_cards),
        "pool_perfect": quality.get("perfect"),
        "pool_grade": quality.get("grade"),
        "quality_dropped": len(quality_dropped),
        "quality_codes": {},
        "filter_funnel": {
            "after_rank_cap": pre_filter,
            "after_customer_facing": after_facing,
            "after_citation": after_cite,
            "after_topup": len(ranked),
        },
        "pool": [asdict(c) for c in pool_cards],
        "suppressed_rule_ids": sorted(feedback_policy.suppressed_rule_ids)[:40],
        **dedupe_meta,
    }
    for v in quality_dropped:
        meta["quality_codes"][v.code] = meta["quality_codes"].get(v.code, 0) + 1
    return cards, meta
