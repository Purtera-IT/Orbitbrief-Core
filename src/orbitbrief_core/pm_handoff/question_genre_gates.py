"""Universal genre / evidence gates for curated customer questions.

Deal-agnostic: lex + atom_type + mode family mismatch. No customer names.
Prevents wrong-genre blockers (AV keep/remove on field-sensor deals,
SAP shipping helpdesk as go-live, user-manual PNs as quote scope) and
promotes assumption↔instruction contradictions into a single blocker.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Iterable, Mapping, Sequence

# Dense field / industrial sensor install — beats weak AV mode from manuals.
FIELD_SENSOR_INSTALL_RE = re.compile(
    r"\b(?:"
    r"tank\s+monitor|tank\s+install|tank\s+survey|telemetry|"
    r"\brtu\b|anova|bulk\s+tank|mini[\-\s]?bulk|"
    r"level\s+sensor|chemical\s+tank|sensor\s+install|"
    r"dpw\d+|dpa\d+|dw900|dpw900"
    r")\b",
    re.I,
)

AV_GENRE_RE = re.compile(
    r"\b(?:"
    r"tv\b|display|codec|soundbar|hdmi|vesa|neat\b|yealink|"
    r"teams\s+room|zoom\s+room|conference\s+room|room\s+bar|"
    r"crestron|extron|biamp|projector|uc\s+bar"
    r")\b",
    re.I,
)

# Helpdesk / shipping / ERP chrome that must never become a field blocker.
HELP_DESK_CHROME_RE = re.compile(
    r"(?i)(?:"
    r"sap\s*s4|shipment\s+and\s+delivery\s+numbers|"
    r"screen\s+shots?\s+of\s+issues|shipping\s+point|"
    r"expedite\s+the\s+remed|user\s+id\b|"
    r"urldefense|proofpoint|mimecast|"
    r"e-?mail\s+message\s+is\s+intended"
    r")"
)

# OEM / user-manual catalog — not a commercial SOW commitment.
USER_MANUAL_CATALOG_RE = re.compile(
    r"(?i)(?:"
    r"user\s+guide|install(?:ation)?\s+guide|assembly\s+guide|"
    r"product\s+sheet|part\s+number\s+d[pw]a?\d+|"
    r"\b\d+\.\d+\.\d+\s+dpa\d+|"  # "3.5.4 DPA968L"
    r"mains\s+power\s+supply\s*\(with\s+heater\)|"
    r"purpose\s*:\s*this\s+guide|this\s+guide\s+allows"
    r")"
)

CHANGE_ORDER_BOILERPLATE_RE = re.compile(
    r"(?i)(?:"
    r"no\s+change\s+or\s+modification\s+to\s+this\s+sow|"
    r"except\s+for\s+billing\s+the\s+actual|"
    r"time\s+and\s+material\s+hours?"
    r")"
)

LIFT_NEG_RE = re.compile(
    r"(?i)\b(?:"
    r"no\s+lift|ladder[\-\s]?only|no\s+(?:scaffold|ladder\s+truck)|"
    r"without\s+a\s+lift|no\s+rented\s+access\s+equipment|"
    r"assume.{0,40}no\s+lift"
    r")\b"
)
LIFT_POS_RE = re.compile(
    r"(?i)\b(?:"
    r"need\s+(?:to\s+)?(?:rent\s+)?a\s+lift|rent\s+a\s+lift|"
    r"scissor\s+lift|boom\s+lift|requires?\s+a\s+lift|"
    r"lift\s+required|need\s+lift"
    r")\b"
)


def _card_text(card: Any) -> str:
    if isinstance(card, Mapping):
        return str(
            card.get("suggested_open_question")
            or card.get("message")
            or card.get("label")
            or ""
        )
    return str(
        getattr(card, "suggested_open_question", None)
        or getattr(card, "message", None)
        or getattr(card, "label", None)
        or ""
    )


def _card_rule(card: Any) -> str:
    if isinstance(card, Mapping):
        return str(card.get("rule_id") or "")
    return str(getattr(card, "rule_id", None) or "")


def _card_sources(card: Any) -> list[Mapping[str, Any]]:
    if isinstance(card, Mapping):
        raw = card.get("sources") or card.get("evidence_sources") or []
    else:
        raw = getattr(card, "sources", None) or getattr(card, "evidence_sources", None) or []
    return [s for s in raw if isinstance(s, Mapping)]


def _source_blob(card: Any) -> str:
    bits: list[str] = []
    if isinstance(card, Mapping):
        bits.append(str(card.get("observed_summary") or ""))
    else:
        bits.append(str(getattr(card, "observed_summary", None) or ""))
    for s in _card_sources(card):
        bits.append(str(s.get("snippet") or s.get("text") or ""))
        bits.append(str(s.get("locator") or ""))
        bits.append(str(s.get("filename") or ""))
    bits.append(_card_text(card))
    return " ".join(bits)


def evidence_is_helpdesk_chrome(text: str) -> bool:
    return bool(HELP_DESK_CHROME_RE.search(text or ""))


def evidence_is_user_manual_catalog(text: str) -> bool:
    return bool(USER_MANUAL_CATALOG_RE.search(text or ""))


def evidence_is_change_order_boilerplate(text: str) -> bool:
    return bool(CHANGE_ORDER_BOILERPLATE_RE.search(text or ""))


def av_template_has_av_evidence(card: Any) -> bool:
    """AV mode templates must cite AV-genre evidence, not SOW billing chrome."""
    blob = _source_blob(card)
    if evidence_is_change_order_boilerplate(blob) and not AV_GENRE_RE.search(blob):
        return False
    # Require at least one source snippet (or question) with AV genre lex.
    for s in _card_sources(card):
        snip = str(s.get("snippet") or "")
        if AV_GENRE_RE.search(snip) and not evidence_is_change_order_boilerplate(snip):
            return True
    return bool(AV_GENRE_RE.search(_card_text(card)))


def should_drop_question_card(
    card: Any,
    *,
    project_mode: str | None = None,
    deal_blob: str | None = None,
) -> str | None:
    """Return drop reason or None to keep. Universal — no deal names."""
    rid = _card_rule(card)
    blob = _source_blob(card)
    mode = (project_mode or "").strip()
    deal = deal_blob or ""

    # Field-sensor deals must not inherit AV keep/remove from manuals / "except for".
    if rid.startswith("mode.av_install.") or rid.startswith("mode.av_"):
        field_n = len(FIELD_SENSOR_INSTALL_RE.findall(deal))
        if field_n >= 3 and mode in {"", "generic", "av_install"}:
            # Dense field-sensor substance → AV templates are wrong genre.
            if not av_template_has_av_evidence(card):
                return "av_template_on_field_sensor_deal"
        if not av_template_has_av_evidence(card):
            return "av_template_without_av_evidence"

    if evidence_is_helpdesk_chrome(blob):
        # Allow only if clear field-install commitment co-occurs in evidence.
        evidence_only = " ".join(
            str(s.get("snippet") or "") for s in _card_sources(card)
        ) or blob
        if not re.search(
            r"(?i)\b(install|survey|mobilize|tank|site\s+access|ladder|ap\b)\b",
            evidence_only,
        ):
            return "helpdesk_chrome_evidence"

    # OEM manuals / part catalogs as commercial scope — not site-access asks.
    if evidence_is_user_manual_catalog(blob) and (
        rid.startswith("scope.")
        or rid.startswith("bom.")
        or "scope" in (str(getattr(card, "label", None) or (card.get("label") if isinstance(card, Mapping) else "") or "")).lower()
        or "part number" in _card_text(card).lower()
        or re.search(r"(?i)\bdpa\d+|\bdpw\d+", _card_text(card))
    ):
        snips = " ".join(str(s.get("snippet") or "") for s in _card_sources(card))
        if evidence_is_user_manual_catalog(snips) or evidence_is_user_manual_catalog(
            str(
                (card.get("observed_summary") if isinstance(card, Mapping) else None)
                or getattr(card, "observed_summary", "")
                or ""
            )
        ):
            # "fixed fee" in the *ask* does not rehabilitate a user-guide PN.
            return "user_manual_catalog_evidence"

    if evidence_is_change_order_boilerplate(blob) and (
        "keep" in rid.lower() or "remove" in (_card_text(card) or "").lower()
    ):
        if not AV_GENRE_RE.search(blob):
            return "change_order_boilerplate_as_keep_remove"

    return None


def filter_question_cards(
    cards: Sequence[Any],
    *,
    project_mode: str | None = None,
    deal_blob: str | None = None,
) -> list[Any]:
    out: list[Any] = []
    for c in cards:
        if should_drop_question_card(c, project_mode=project_mode, deal_blob=deal_blob):
            continue
        out.append(c)
    return out


def _atom_text(atom: Mapping[str, Any]) -> str:
    for key in ("text", "raw_text", "normalized_text", "claim"):
        val = atom.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _atom_type(atom: Mapping[str, Any]) -> str:
    return str(atom.get("atom_type") or atom.get("type") or "").strip().lower()


def detect_lift_access_conflicts(
    atoms: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Emit one blocker when assumptions say no-lift but instructions need a lift."""
    neg: list[tuple[str, str, Mapping[str, Any]]] = []
    pos: list[tuple[str, str, Mapping[str, Any]]] = []
    for atom in atoms:
        if not isinstance(atom, Mapping):
            continue
        text = _atom_text(atom)
        if not text:
            continue
        at = _atom_type(atom)
        aid = str(atom.get("id") or atom.get("atom_id") or "")
        if LIFT_NEG_RE.search(text):
            neg.append((aid, text, atom))
        if LIFT_POS_RE.search(text):
            # Prefer instruction / constraint over manual noise
            if at in {"customer_instruction", "constraint", "assumption", "risk", ""} or LIFT_POS_RE.search(
                text
            ):
                pos.append((aid, text, atom))
    if not neg or not pos:
        return []

    neg_t = neg[0][1]
    pos_t = pos[0][1]
    # Avoid self-conflict inside the same sentence.
    if neg_t == pos_t:
        return []

    def _src(atom: Mapping[str, Any], text: str) -> dict[str, Any]:
        return {
            "filename": str(
                atom.get("filename")
                or atom.get("artifact_id")
                or atom.get("doc_id")
                or "deal-evidence"
            ),
            "artifact_id": str(atom.get("artifact_id") or ""),
            "atom_id": str(atom.get("id") or atom.get("atom_id") or ""),
            "snippet": text[:280],
            "locator": _atom_type(atom) or "conflict",
            "match_score": 0.95,
            "media": "text",
        }

    fp = hashlib.sha1(f"{neg_t[:80]}|{pos_t[:80]}".encode("utf-8")).hexdigest()[:10]
    return [
        {
            "rule_id": f"conflict.lift_access.{fp}",
            "domain_id": "operations",
            "label": "Lift / access equipment conflict",
            "severity": "blocker",
            "message": (
                "Intake contradicts itself on lift / rented access equipment — "
                "one source says none required; another says a lift is needed."
            ),
            "suggested_open_question": (
                "Which is authoritative for install planning: the no-lift / "
                "ladder-only assumption, or the instruction that a lift must be rented?"
            ),
            "observed_summary": (
                f"Conflict: NO-LIFT «{neg_t[:120]}» vs NEED-LIFT «{pos_t[:120]}»"
            ),
            "sources": [_src(neg[0][2], neg_t), _src(pos[0][2], pos_t)],
        }
    ]


def detect_address_roster_conflict(
    atoms: Iterable[Mapping[str, Any]],
    *,
    publishable_site_names: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """When customer contests the address list, keep a sharp roster authority ask.

    Does not invent sites — only fires when a customer_instruction already
    contests addresses OR multiple distinct state/city clusters appear with
    a customer contest signal.
    """
    contest = None
    for atom in atoms:
        if not isinstance(atom, Mapping):
            continue
        text = _atom_text(atom)
        if _atom_type(atom) == "customer_instruction" and re.search(
            r"(?i)addresses?/locations?\s+are\s+different|confirm\s+if\s+these\s+are\s+the\s+correct\s+addresses",
            text,
        ):
            contest = (atom, text)
            break
    if not contest:
        return []
    atom, text = contest
    names = [n for n in (publishable_site_names or []) if n]
    name_bit = f" (publishable roster: {', '.join(names[:4])})" if names else ""
    return [
        {
            "rule_id": "conflict.site_address_authority",
            "domain_id": "sites",
            "label": "Authoritative site address list",
            "severity": "blocker",
            "message": (
                "Customer contested the address / location list against the kit"
                f"{name_bit}."
            ),
            "suggested_open_question": (
                "Which site address list is authoritative for this quote wave — "
                "the customer's list or the kit list — and which locations drop?"
            ),
            "observed_summary": f"Evidence: customer_instruction: {text[:180]}",
            "sources": [
                {
                    "filename": str(atom.get("filename") or atom.get("artifact_id") or "email"),
                    "artifact_id": str(atom.get("artifact_id") or ""),
                    "atom_id": str(atom.get("id") or atom.get("atom_id") or ""),
                    "snippet": text[:280],
                    "locator": "customer_instruction",
                    "match_score": 0.95,
                    "media": "text",
                }
            ],
        }
    ]


__all__ = [
    "FIELD_SENSOR_INSTALL_RE",
    "detect_address_roster_conflict",
    "detect_lift_access_conflicts",
    "filter_question_cards",
    "should_drop_question_card",
]
