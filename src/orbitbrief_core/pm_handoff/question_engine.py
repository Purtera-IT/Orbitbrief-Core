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
from orbitbrief_core.validator.sow_completeness import (
    _NETWORK_INSTALL_EVIDENCE_RE,
    _atom_text,
)

DEFAULT_QUESTION_CAP = 8
MIN_SAFETY_NET_IF_EMPTY = 2

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

# Ops / ALM / staff families that must never promote on edge-install deals.
_INSTALL_BANNED_RULE_PREFIXES = (
    "network_maintenance.firmware",
    "network_maintenance.coverage",
    "network_maintenance.patch",
    "network_maintenance.oem",
    "network_maintenance.vlan_port_audit",
    "network_maintenance.circuit_demarc",
    "alm.",
    "staff_augmentation.",
)

_WIRELESS_INSTALL_RE = re.compile(
    r"\b(?:access\s+points?|aps?\b|wifi|wi[\-\s]?fi|wlan|ssid|heatmap|ap[\-\s]?on[\-\s]?a[\-\s]?stick)\b",
    re.I,
)
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
    r"\b(?:audio[\-\s]?visual|projector|dsp\b|crestron|extron|conference\s+room\s+av)\b",
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
    primary = str(sr.get("primary") or "").strip()
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

    if primary == "wireless" or _WIRELESS_INSTALL_RE.search(text or ""):
        if _CONFIG_ONLY_RE.search(text or ""):
            return MODE_WIRELESS_CONFIG
        return MODE_WIRELESS_INSTALL

    if primary in {"low_voltage_cabling", "cabling"} or _CABLING_RE.search(text or ""):
        return MODE_CABLING

    if primary == "alm" or _ALM_RE.search(text or ""):
        return MODE_ALM

    if primary == "staff_augmentation" or _STAFF_AUG_RE.search(text or ""):
        # Remote-hands on network install already returned above.
        return MODE_STAFF_AUG

    if primary == "audio_visual" or _AV_RE.search(text or ""):
        return MODE_AV

    if primary == "access_control" or _ACCESS_RE.search(text or ""):
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
    )
    if any(b in low for b in banned):
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


def _candidates_from_evidence_atoms(
    atoms: Iterable[Mapping[str, Any]],
    *,
    project_mode: str,
) -> list[QuestionCandidate]:
    out: list[QuestionCandidate] = []
    seen_fp: set[str] = set()
    for atom in atoms:
        if not isinstance(atom, Mapping):
            continue
        atype = str(atom.get("atom_type") or "").lower()
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
                r"\b(gold[\-\s]?image|firmware\s+baseline|vlan\s+audit|oem\s+tac|smartnet)\b",
                text,
                re.I,
            ):
                continue
        fp = fingerprint_question(text)
        if fp in seen_fp:
            continue
        seen_fp.add(fp)
        aid = str(atom.get("id") or atom.get("atom_id") or "")
        pm_q = _to_pm_question(text)
        if not (pm_q or "").strip():
            continue
        severity = "blocker" if atype in {"risk", "missing_info"} else "warning"
        # Prefer open_question / decision; demote still-casual rewrites slightly
        score = 0.92 if atype == "open_question" else 0.85 if atype == "decision" else 0.72
        if pm_q != text and atype == "open_question":
            score = 0.9
        label = {
            "open_question": "Open project question",
            "decision": "Decision still open",
            "risk": "Risk needs owner answer",
            "action_item": "Action needs clarification",
        }.get(atype, "Project clarification")
        out.append(
            QuestionCandidate(
                rule_id=f"evidence.{atype}.{fp[:48] or aid or 'q'}",
                domain_id="project",
                label=label,
                severity=severity,
                message=text,
                suggested_open_question=pm_q,
                observed_summary=f"From {atype or 'evidence'} atom",
                source="evidence",
                score=score,
                evidence_atom_ids=[aid] if aid else [],
                project_mode=project_mode,
            )
        )
    return out


def _to_pm_question(text: str) -> str:
    """Normalize atom prose into a PM-facing question."""
    t = re.sub(r"\s+", " ", (text or "").strip())
    if not t:
        return t
    low = t.lower()
    # Lift casual transcript into PM voice
    if "one device per site" in low or low.startswith("once we know"):
        return "Confirm topology: one edge device per site, or a shared/hub model?"
    if "copy of those sites" in low:
        return ""  # suppressed as non-PM
    if "copy of their sop" in low or ("sop" in low and "copy" in low):
        return "Can we get the customer's SOP before the first site, and who owns revisions?"
    if "who do you get approval from" in low or low.startswith("who do you get approval"):
        return "Who is the customer approval authority for scope/change decisions on this engagement?"
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
            "Which sites are in this phase vs deferred (e.g. Montreal / CDW CA paper), "
            "and who confirms the final in-scope set?"
        ),
        message="Skip/defer language exists for at least one site; phase boundary needs a hard yes/no.",
        trigger=re.compile(
            r"(?:will\s+(?:probaly|probably)?\s*not\s+do|montreal|keep\s+(?:everything\s+)?on\s+us\s+paper|"
            r"avoid\s+cdw\s+ca|etobicoke\s+has\s+already\s+been\s+done)",
            re.I,
        ),
        score=0.9,
    ),
    _ModeTemplate(
        rule_id="mode.network_edge_install.first_survey_site",
        domain_id="network_edge_install",
        label="First survey / walkthrough site",
        question="Which site is the first walkthrough / site survey, and who schedules customer access?",
        message="Site survey is planned but the first site is not locked.",
        trigger=re.compile(
            r"(?:site\s+survey|walkthrough|first\s+site\s+survey|which\s+one\s+of\s+these\s+sites)",
            re.I,
        ),
        answered_by=re.compile(
            r"\b(?:survey\s+site\s*(?:is|=)|walkthrough\s+at\s+[A-Z]|first\s+site:\s*)\b",
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
        label="Circuit readiness per site",
        question="Which sites have circuits turned up and ready for smart-hands install, and which are still waiting on the carrier?",
        message="Circuit spin-up is a schedule dependency for remote/smart hands.",
        trigger=re.compile(
            r"(?:turning\s+on\s+the\s+circuits|circuits?\s+spun\s+up|circuit(?:s)?\s+at\s+(?:each|these))",
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
            trigger=re.compile(r"\b(?:access\s+point|aps?\b|wifi|wlan)\b", re.I),
            answered_by=re.compile(r"\b\d+\s*(?:x\s*)?(?:aps?|access\s+points?)\b", re.I),
            severity="blocker",
            score=0.93,
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


def _candidates_from_mode_templates(
    *,
    project_mode: str,
    blob: str,
) -> list[QuestionCandidate]:
    out: list[QuestionCandidate] = []
    for tmpl in _MODE_TEMPLATES.get(project_mode, ()):
        if not tmpl.trigger.search(blob or ""):
            continue
        if tmpl.answered_by is not None and tmpl.answered_by.search(blob or ""):
            continue
        out.append(
            QuestionCandidate(
                rule_id=tmpl.rule_id,
                domain_id=tmpl.domain_id,
                label=tmpl.label,
                severity=tmpl.severity,
                message=tmpl.message,
                suggested_open_question=tmpl.question,
                observed_summary=f"Mode template for {project_mode}",
                source="mode_template",
                score=tmpl.score,
                project_mode=project_mode,
            )
        )
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
    out: list[QuestionCandidate] = []
    for c in candidates:
        fp = fingerprint_question(c.suggested_open_question or c.message)
        if c.rule_id in policy.suppressed_rule_ids:
            continue
        if fp and fp in policy.suppressed_fingerprints:
            continue
        if (project_mode, c.rule_id) in policy.suppressed_mode_rules:
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


def rank_and_cap(
    candidates: list[QuestionCandidate],
    *,
    cap: int = DEFAULT_QUESTION_CAP,
) -> list[QuestionCandidate]:
    def sort_key(c: QuestionCandidate) -> tuple:
        return (
            SEVERITY_SORT.get(c.severity, 9),
            -c.score,
            0 if c.source in {"evidence", "pm_gold"} else 1 if c.source == "mode_template" else 2,
            c.suggested_open_question,
        )

    # Dedupe by fingerprint AND near-duplicate intent (same family stem).
    best: dict[str, QuestionCandidate] = {}
    intent_best: dict[str, QuestionCandidate] = {}

    def intent_key(c: QuestionCandidate) -> str:
        q = (c.suggested_open_question or c.message or "").lower()
        if "topology" in q or "per site" in q or ("hub" in q and "spoke" in q):
            return "topology"
        if "sop" in q and ("acceptance" in q or "sign" in q or "poc" in q):
            return "acceptance_sop"
        if "sop" in q:
            return "sop_receipt"
        if "montreal" in q or "deferred" in q or "phase vs" in q:
            return "phase_exclusions"
        if "survey" in q and ("charge" in q or "commercial" in q or "fee" in q):
            return "survey_commercial"
        if "survey" in q or "walkthrough" in q:
            return "first_survey"
        if "circuit" in q:
            return "circuit_ready"
        if "smart-hands" in q or "smart hands" in q or "remote hands" in q:
            return "smart_hands"
        if "approval" in q or "approv" in q:
            return "approval"
        return fingerprint_question(q)

    for c in candidates:
        fp = fingerprint_question(c.suggested_open_question or c.message)
        if not fp:
            continue
        prev = best.get(fp)
        if prev is None or c.score > prev.score or (
            c.score == prev.score and SEVERITY_SORT.get(c.severity, 9) < SEVERITY_SORT.get(prev.severity, 9)
        ):
            best[fp] = c
        ik = intent_key(c)
        prev_i = intent_best.get(ik)
        if prev_i is None or c.score > prev_i.score or (
            c.score == prev_i.score and SEVERITY_SORT.get(c.severity, 9) < SEVERITY_SORT.get(prev_i.severity, 9)
        ):
            intent_best[ik] = c

    # Prefer intent dedupe (collapses evidence+template duplicates).
    ranked = sorted(intent_best.values(), key=sort_key)
    return ranked[: max(1, cap)]


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

    candidates: list[QuestionCandidate] = []
    candidates.extend(_candidates_from_evidence_atoms(atoms, project_mode=project_mode))
    candidates.extend(_candidates_from_mode_templates(project_mode=project_mode, blob=blob))
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
        candidates.extend(
            _yaml_safety_net(
                gaps,
                project_mode=project_mode,
                existing_rule_ids=existing,
                max_add=MIN_SAFETY_NET_IF_EMPTY,
            )
        )

    ranked = rank_and_cap(candidates, cap=cap)
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
        "cap": cap,
        "suppressed_rule_ids": sorted(feedback_policy.suppressed_rule_ids)[:40],
    }
    return cards, meta
