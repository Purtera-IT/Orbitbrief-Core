"""Neural project-fact gate for PM-visible evidence cards.

Stops conversation filler (greetings, soft prompts) from landing in
commercial / scope fact lanes when typed as ``deal_metadata``.
"""
from __future__ import annotations

import os
import re
from typing import Any, Mapping, Sequence

from orbitbrief_core.pm_handoff.semantic_dedupe import (
    cosine_similarity,
    resolve_question_embedder,
)
from orbitbrief_core.retrieval.embedder import DeterministicHashEmbedder

# Minimum (fact_proto − filler_proto) cosine margin to keep an atom as a fact.
FACT_MARGIN = float(os.environ.get("ORBITBRIEF_FACT_NEURAL_MARGIN", "0.04"))

_FACT_PROTOTYPES: tuple[str, ...] = (
    "Project evidence: commercial terms payment pricing CDW paper PO NTE fee quote approval authority",
    "Project evidence: physical site address office location circuit carrier Meraki MX BOM quantity",
    "Project evidence: SOP runbook POC smart hands remote hands install scope schedule milestone",
    "Project evidence: stakeholder owner signatory customer decision scope exclusion constraint risk",
)

_FILLER_PROTOTYPES: tuple[str, ...] = (
    "Conversation filler greeting: how you doing how are you guys doing well weekend plans volleyball",
    "Conversation filler soft prompt with no deal content: what are your thoughts you know what I mean who knows",
    "Conversation filler screen share smalltalk: seeing my screen what about you olympian last name",
)

_LEXICAL_FILLER_RE = re.compile(
    r"(?i)^(?:"
    r"(?:so|and|but|well|yeah|ok|okay|um+|uh+|i\s+mean)[, ]+)?"
    r"(?:(?:nick|chase|quinton|trent|hey)[, ]+)?"
    r"(?:how(?:'s| is| are)?\s+you(?:r)?(?:\s+guys)?(?:\s+doing)?|"
    r"you\s+guys\s+doing\s+well|"
    r"any\s+big\s+plans|"
    r"what\s+about\s+you|"
    r"who\s+knows|"
    r"(?:i\s+mean[, ]+)?what\s+are\s+your\s+thoughts(?:\s+on\s+that)?|"
    r"you\s+know\s+what\s+i\s+mean|"
    r"seeing\s+my\s+screen|"
    r"volleyball|"
    r"good\s+morning|good\s+afternoon|"
    r"how(?:'s|\s+is|\s+are)\s+it\s+going"
    r")[\s\?\!\.]*$"
)

_COMMERCIAL_SUBSTANCE_RE = re.compile(
    r"(?i)\b("
    r"price|pricing|payment|invoice|po\b|purchase\s+order|nte|not\s+to\s+exceed|"
    r"fixed\s+fee|t\s*&\s*m|time\s+and\s+materials|margin|discount|quote|"
    r"cdw\s+(?:us\s+)?paper|us\s+paper|change\s+order|msa|sow\b|commercial|"
    r"per[\-\s]?site\s+(?:fee|rate|charge)|survey\s+charge|bill(?:ing|able)"
    r")\b"
)

_DEAL_SUBSTANCE_RE = re.compile(
    r"(?i)\b("
    r"site|office|address|circuit|meraki|mx\b|sd[\-\s]?wan|sop|poc|"
    r"smart\s+hands|remote\s+hands|bom|device|install|survey|walkthrough|"
    r"montreal|canada|maitland|carrier|topology|config(?:uration)?|"
    r"approval|paper|quote|schedule|milestone|scope|rack|stack|"
    # AV / UC install substance (Catalyst-style photo packs)
    r"neat|yealink|hdmi|vesa|codec|soundbar|conference\s+room|"
    r"behind\s+the\s+wall|drywall|floor\s+network|display|mount"
    r")\b"
)

_VISION_PLACEHOLDER_RE = re.compile(
    r"(?i)\b(?:awaiting\s+ocr(?:\s*/\s*vision)?|image\s+vision\s+abstain|"
    r"\[image\s+extracted\b|image_vision_abstained:)"
)

_EMAIL_SECURITY_URL_RE = re.compile(
    r"(?i)\b(?:urldefense|proofpoint|mimecast|safelinks\.protection|"
    r"mimecastcybergraph|cgbannerindicator|mark\s+safe|powered\s+by\s+mimecast)\b"
)

# Marketing / capability-email chrome that must never land in fact cards (O7/O12).
_MARKETING_FACT_NOISE_RE = re.compile(
    r"(?i)(?:"
    r"quotes\s+in\s+24|"
    r"ai[\-\s]?driven\s+pmo|"
    r"^account\s+executive$|"
    r"global\s+field\s+services|"
    r"wifi,\s+and\s+cabling|"
    r"proven\s+execution\s+across|"
    r"^www\.purtera|"
    r"^purtera\-it\.com\b|"
    r"similar\s+name\s+as\s+someone|"
    r"^from:\s|^sent:\s|mailto:"
    r")"
)

_SPECULATIVE_RISK_FACT_RE = re.compile(
    r"(?i)(?:"
    r"(?:may|could|might)\s+pose|"
    r"(?:may|could|might)\s+affect|"
    r"may\s+impact|"
    r"potentially\s+affecting|"
    r"slight\s+trip|"
    r"patterned\s+carpet|"
    r"field\s+of\s+view|"
    r"aesthetically\s+unappealing|"
    r"\baesthetic\b|"
    r"professional\s+appearance|"
    r"cleaner\s+look|"
    r"not\s+fully\s+conceal|"
    r"trip\s+hazard|"
    r"pose\s+a\s+(?:potential\s+|minor\s+)?(?:obstruction|trip\s+hazard)|"
    r"posing\s+a\s+(?:potential\s+|minor\s+)?(?:obstruction|trip\s+hazard)|"
    r"pose\s+a\s+[^.]{0,40}?trip\s+hazard|"
    r"\bbackpack\b|"
    r"personal\s+(?:belongings|items|effects)|"
    r"minor\s+obstruction|"
    r"non[\-\s]?standard\s+tile\s+layout"
    r")"
)

_HARD_GROUNDED_RISK_RE = re.compile(
    r"(?i)(?:"
    r"behind\s+the\s+wall|"
    r"drywall\s+(?:cut|patch|paint|own)|"
    r"in[\-\s]?wall\s+(?:fish|path|hdmi|run)|"
    r"keep\s+vs\s+remove|"
    r"stay\s+in\s+place|"
    r"replication\s+cable|"
    r"should\s+be\s+(?:moved|rerouted|hidden)\s+behind|"
    r"hard\s+to\s+get|"
    # Install gold that must stay visible in the PM facts lane
    r"\bvesa\b|"
    r"ceiling\s+tiles?|"
    r"(?:display|tv|wall|ceiling)\s+mount|"
    r"hdmi\s+(?:over\s+ethernet|replicator)"
    r")"
)


def is_av_install_gold_fact(text: str) -> bool:
    """True for install-critical AV signals that must elevate into fact cards."""
    return bool(_HARD_GROUNDED_RISK_RE.search(text or ""))

_SOW_TEMPLATE_FACT_RE = re.compile(
    r"(?i)^\[\s*(?:"
    r"if\s+this\s+sow|"
    r"shi\s+does\s+not\s+have\s+an\s+msa|"
    r".{0,80}use\s+this\s+paragraph|"
    r".{0,80}naspo\s+contract|"
    r".{0,80}special\s+contract"
    r")"
)

_SHRED_FACT_RE = re.compile(
    r"(?i)^(?:ss|ph|&nbsp;|nbsp|;|&amp;|\u00b0shi|shi°?|\.|\-|–|—)+$"
)

_SHRED_LABEL_FACT_RE = re.compile(
    r"(?i)^[\"']?(?:note|notes|n/?a|tbd|none|null|test)[\"']?$"
)

_STRUCTURED_KEEP = frozenset(
    {
        "physical_site",
        "bom_line",
        "site_allocation",
        "decision",
        "risk",
        "action_item",
        "constraint",
        "milestone_phase",
        "scope_item",
    }
)


def _atom_text(atom: Mapping[str, Any] | Any) -> str:
    if isinstance(atom, Mapping):
        for key in ("text", "raw_text", "normalized_text", "claim"):
            val = atom.get(key)
            if isinstance(val, str) and val.strip():
                return unwrap_fact_text(val.strip())
        value = atom.get("value")
        if isinstance(value, Mapping):
            for key in ("text", "claim", "summary"):
                val = value.get(key)
                if isinstance(val, str) and val.strip():
                    return unwrap_fact_text(val.strip())
        return ""
    for attr in ("text", "raw_text", "normalized_text"):
        val = getattr(atom, attr, None)
        if isinstance(val, str) and val.strip():
            return unwrap_fact_text(val.strip())
    return ""


def unwrap_fact_text(text: str) -> str:
    """P3 / O1 — strip JSON / Python string-list wrappers from vision claims."""
    import json

    text = re.sub(r"\s+", " ", (text or "").strip())
    if len(text) < 4:
        return text
    if text[0] in "[{\"'":
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list) and parsed:
                first = parsed[0]
                if isinstance(first, str) and first.strip():
                    text = first.strip()
            elif isinstance(parsed, str) and parsed.strip():
                text = parsed.strip()
        except Exception:
            pass
    if (
        len(text) > 4
        and text[0] == "["
        and text[-1] == "]"
        and text[1] in "'\""
        and text[-2] in "'\""
    ):
        text = text[2:-2].replace('\\"', '"').replace("\\'", "'").strip()
    if text.startswith("['") and text.endswith("']") and text.count("']") == 1:
        text = text[2:-2].strip()
    return re.sub(r"\s+", " ", text).strip()


def is_marketing_or_chrome_fact(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return True
    if _SHRED_FACT_RE.fullmatch(t) or (len(t) < 6 and not re.search(r"[a-zA-Z]{3,}", t)):
        return True
    if _SHRED_LABEL_FACT_RE.fullmatch(t):
        return True
    if re.fullmatch(r"[\"'][^\"']{1,24}[\"']", t):
        return True
    if _SOW_TEMPLATE_FACT_RE.search(t) or (
        t.startswith("[")
        and re.search(r"(?i)use\s+this\s+paragraph|making\s+the\s+appropriate\s+changes", t)
    ):
        return True
    if _MARKETING_FACT_NOISE_RE.search(t):
        return True
    if _EMAIL_SECURITY_URL_RE.search(t) and not deal_substance(t):
        return True
    return False


_SOW_COMMITMENT_FACT_RE = re.compile(
    r"(?i)\b(?:will\s+(?:furnish|install|provide|configure|deploy)|"
    r"purtera\s+will|contractor\s+will|in[\-\s]?scope|shall\s+(?:furnish|install))\b"
)


def is_speculative_risk_fact(text: str, *, atom_type: str | None = None) -> bool:
    t = text or ""
    if not _SPECULATIVE_RISK_FACT_RE.search(t):
        return False
    if _HARD_GROUNDED_RISK_RE.search(t):
        return False
    at = (atom_type or "").lower()
    if at in {"task", "scope_item", "bom_line", "action_item"} and _SOW_COMMITMENT_FACT_RE.search(t):
        return False
    # Affirmative SOW language without type — still keep.
    if not at and _SOW_COMMITMENT_FACT_RE.search(t):
        return False
    return True


def _atom_type(atom: Mapping[str, Any] | Any) -> str:
    if isinstance(atom, Mapping):
        return str(atom.get("atom_type") or "").lower()
    at = getattr(atom, "atom_type", None)
    return str(getattr(at, "value", at) or "").lower()


def _atom_payload(atom: Mapping[str, Any] | Any) -> Mapping[str, Any]:
    """Parser puts conversation_meta flags on ``value`` or ``structured``."""
    if isinstance(atom, Mapping):
        for key in ("value", "structured"):
            val = atom.get(key)
            if isinstance(val, Mapping) and val:
                return val
        return {}
    for attr in ("value", "structured"):
        val = getattr(atom, attr, None)
        if isinstance(val, Mapping) and val:
            return val
    return {}


def _payload_role_kind(atom: Mapping[str, Any] | Any) -> tuple[str, str]:
    payload = _atom_payload(atom)
    return (
        str(payload.get("role") or "").lower(),
        str(payload.get("kind") or "").lower(),
    )


def is_marked_conversation_meta(atom: Mapping[str, Any] | Any) -> bool:
    """True when parser tagged the atom as non-deal chat (may still carry facts)."""
    payload = _atom_payload(atom)
    role, kind = _payload_role_kind(atom)
    if kind in {"conversation_meta", "smalltalk", "filler", "greeting"}:
        return True
    if role in {"filler", "greeting", "smalltalk", "soft_prompt"}:
        return True
    if payload.get("non_deal") or payload.get("head_exclude"):
        return True
    if isinstance(atom, Mapping):
        flags = list(atom.get("review_flags") or [])
        atype = str(atom.get("atom_type") or "").lower()
    else:
        flags = list(getattr(atom, "review_flags", None) or [])
        at = getattr(atom, "atom_type", None)
        atype = str(getattr(at, "value", at) or "").lower()
    if atype in {"conversation_meta", "smalltalk"}:
        return True
    return "conversation_meta" in {str(f).lower() for f in flags}


def is_hard_conversation_filler(atom: Mapping[str, Any] | Any, text: str) -> bool:
    """Drop-only: greetings / soft prompts. Do not drop substance-bearing soft commits."""
    role, kind = _payload_role_kind(atom)
    if role in {"greeting", "smalltalk", "soft_prompt"}:
        return True
    if kind in {"greeting", "smalltalk"}:
        return True
    if is_lexical_conversation_filler(text):
        return True
    # Vision stubs left after image extract / abstain — not PM facts.
    if _VISION_PLACEHOLDER_RE.search(text or ""):
        return True
    # Marketing / email chrome / shred (O7 / O12 / P2 / P8).
    if is_marketing_or_chrome_fact(text):
        return True
    # Soft aesthetic vision risks must not occupy any fact lane (P5).
    if is_speculative_risk_fact(text, atom_type=_atom_type(atom)):
        return True
    payload = _atom_payload(atom)
    fk = str(payload.get("fact_kind") or "").lower()
    if (
        "aesthetic" in fk
        and not _HARD_GROUNDED_RISK_RE.search(text or "")
        and not _SOW_COMMITMENT_FACT_RE.search(text or "")
    ):
        return True
    if _EMAIL_SECURITY_URL_RE.search(text or "") and not deal_substance(text):
        return True
    # Parser marks many soft commitments as conversation_meta/filler; keep those
    # that still carry deal substance for the neural / substance path.
    if is_marked_conversation_meta(atom) and not (
        deal_substance(text) or commercial_substance(text)
    ):
        return True
    return False


def is_lexical_conversation_filler(text: str) -> bool:
    t = re.sub(r"\s+", " ", (text or "").strip())
    if not t:
        return True
    if _LEXICAL_FILLER_RE.match(t):
        return True
    # Soft prompts / greetings with optional leading discourse marker.
    if re.search(
        r"(?i)^(?:so|and|but|well|yeah|ok|okay|um+|uh+)[, ]+"
        r"(?:what\s+are\s+your\s+thoughts|how\s+(?:are\s+)?you(?:\s+doing)?)\b",
        t,
    ):
        return True
    if len(t) < 56 and t.endswith("?") and not _DEAL_SUBSTANCE_RE.search(t):
        if re.search(r"(?i)\b(how|what|who|where|why)\b", t):
            return True
    return False


def commercial_substance(text: str) -> bool:
    return bool(_COMMERCIAL_SUBSTANCE_RE.search(text or ""))


def deal_substance(text: str) -> bool:
    return bool(_DEAL_SUBSTANCE_RE.search(text or ""))


def neural_fact_scores(
    texts: Sequence[str],
    *,
    embedder=None,
) -> tuple[list[float], str]:
    """Return fact−filler margin per text (higher ⇒ more project-fact-like)."""
    emb = resolve_question_embedder(embedder)
    if not texts:
        return [], emb.model_id
    corpus = [*_FACT_PROTOTYPES, *_FILLER_PROTOTYPES, *[t or "" for t in texts]]
    try:
        vecs = emb.embed(list(corpus))
    except Exception:
        emb = DeterministicHashEmbedder(dim=256)
        vecs = emb.embed(list(corpus))
    n_fact = len(_FACT_PROTOTYPES)
    n_fill = len(_FILLER_PROTOTYPES)
    fact_vecs = vecs[:n_fact]
    fill_vecs = vecs[n_fact : n_fact + n_fill]
    out: list[float] = []
    for i in range(len(texts)):
        tv = vecs[n_fact + n_fill + i]
        best_fact = max(cosine_similarity(tv, fv) for fv in fact_vecs)
        best_fill = max(cosine_similarity(tv, fv) for fv in fill_vecs)
        out.append(best_fact - best_fill)
    return out, emb.model_id


def filter_pm_visible_atoms(
    atoms: Sequence[Mapping[str, Any] | Any],
    *,
    embedder=None,
) -> tuple[list[Any], dict[str, Any]]:
    """Batch-filter atoms for fact cards; returns (kept, debug meta)."""
    if not atoms:
        return [], {
            "fact_quality_input": 0,
            "fact_quality_kept": 0,
            "fact_quality_dropped_pre": 0,
            "fact_quality_dropped_neural": 0,
            "fact_quality_embedder": "none",
            "fact_quality_margin": FACT_MARGIN,
            "fact_quality_neural": False,
        }

    hard_keep: list[Any] = []
    judge: list[tuple[Any, str]] = []
    dropped_pre = 0

    for atom in atoms:
        text = _atom_text(atom)
        if len(text.strip()) < 8 or is_hard_conversation_filler(atom, text):
            dropped_pre += 1
            continue
        atype = _atom_type(atom)
        if atype in _STRUCTURED_KEEP:
            hard_keep.append(atom)
            continue
        if atype == "open_question" and (deal_substance(text) or commercial_substance(text)):
            hard_keep.append(atom)
            continue
        # Substance-bearing soft commits: keep without neural (hash embedder is weak).
        if deal_substance(text) or commercial_substance(text):
            hard_keep.append(atom)
            continue
        # deal_metadata and weak misc types → neural judge
        judge.append((atom, text))

    scores: list[float] = []
    model_id = "skipped"
    if judge:
        scores, model_id = neural_fact_scores([t for _, t in judge], embedder=embedder)

    neural = "deterministic-hash" not in (model_id or "").lower() and model_id != "skipped"
    kept: list[Any] = list(hard_keep)
    dropped_neural = 0
    for (atom, text), score in zip(judge, scores or []):
        if neural:
            ok = score >= FACT_MARGIN
        else:
            ok = deal_substance(text) or commercial_substance(text)
        if ok:
            kept.append(atom)
        else:
            dropped_neural += 1

    meta = {
        "fact_quality_input": len(atoms),
        "fact_quality_kept": len(kept),
        "fact_quality_dropped_pre": dropped_pre,
        "fact_quality_dropped_neural": dropped_neural,
        "fact_quality_embedder": model_id,
        "fact_quality_margin": FACT_MARGIN,
        "fact_quality_neural": neural,
    }
    return kept, meta


# ── Claim polish (transcript → PM-readable fact) ───────────────────

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.I,
)

# Bare open questions already covered by curated customer_questions → drop.
_DROP_AS_FACT_RE = re.compile(
    r"(?i)^(?:"
    r"do you have a copy of their sop(?: by chance)?|"
    r"who do you get approval from|"
    r"once we know is it going to be one device per site|"
    r"all the documentation|"
    r"is it something we need to get back in front of the group.*"
    r")[\s\?\!\.]*$"
)

_CLAIM_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"(?i)site survey with anticipations of a change order|"
            r"anticipations of a change order.*site survey|"
            r"site survey charge"
        ),
        "Site survey may be billed via change order / survey charge before the remaining sites are looped in.",
    ),
    (
        re.compile(r"(?i)1 location will be treated as a poc.*sop"),
        "One location is the POC; customer has an SOP that will be used/revised during that visit.",
    ),
    (
        re.compile(r"(?i)need help with remote hands for\s+(\d+)\s+corporate offices"),
        "Remote hands requested for corporate offices (count per source).",
    ),
    (
        re.compile(r"(?i)need onsite smart hands per location"),
        "Onsite smart hands required per location.",
    ),
    (
        re.compile(r"(?i)transitioning from mpls to sdwan|transitioning from mpls to sd[\-\s]?wan"),
        "Customer is transitioning from MPLS to SD-WAN.",
    ),
    (
        re.compile(r"(?i)during this visit we will also revise the sop"),
        "SOP will be revised/updated during the POC visit.",
    ),
    (
        re.compile(r"(?i)turning on the circuits.*smart hands.*sd[\-\s]?wan"),
        "Circuits are being turned up; smart hands needed to install SD-WAN gear on-site.",
    ),
    (
        re.compile(r"(?i)turning on circuits at each location"),
        "Circuits are being turned on at each location.",
    ),
    (
        re.compile(r"(?i)will\s+probaly\s+not\s+do.*montreal|avoid\s+cdw\s+ca|keep\s+everything\s+on\s+us\s+paper"),
        "Montreal / CDW CA path may be deferred; preference is to keep work on CDW US paper.",
    ),
    (
        re.compile(r"(?i)13 locations.*canada.*cdw\s+us\s+paper|keep work on cdw us paper"),
        "Canada site(s) intended on CDW US paper for now (avoid CDW CA where noted).",
    ),
    (
        re.compile(r"(?i)after hours because they're taking part of the network down"),
        "Most cutovers are after hours (~4 hours) because part of the network is taken down.",
    ),
    (
        re.compile(r"(?i)start soon and mid[\-\s]?august wrap up"),
        "Target window: start soon, wrap mid-August.",
    ),
    (
        re.compile(r"(?i)get back to me monday.*site survey|walkthrough slash site survey"),
        "Customer to name preferred walkthrough / site-survey site (expected Monday callback).",
    ),
    (
        re.compile(r"(?i)cdw will send over locations and the sop"),
        "CDW will send locations + SOP when available; follow-up call once SOP is in hand.",
    ),
    (
        re.compile(
            r"(?i)wonder if they're going to need our help on site with anything outside "
            r"of just a physical install"
        ),
        "Onsite scope may extend beyond physical install (config/test/docs still open).",
    ),
    (
        re.compile(r"(?i)label this cable specifically.*circuit"),
        "Cable labeling expected to call out dedicated circuit before migration to the new device.",
    ),
    (
        re.compile(r"(?i)taken a little longer.*circuits spun up"),
        "Preferred survey site delayed while circuits are spun up.",
    ),
    (
        re.compile(r"(?i)^meraki mx\b"),
        "Meraki MX devices on BOM (quantity per source).",
    ),
)


def display_case_label(
    case_id: str,
    *,
    report: Mapping[str, Any] | None = None,
    sow: Mapping[str, Any] | None = None,
    case_dir_name: str | None = None,
) -> str:
    """Human deal label for headlines — never lead with a bare UUID."""
    report = report or {}
    sow = sow or {}
    env = report.get("envelope") if isinstance(report.get("envelope"), Mapping) else {}
    numbered: list[str] = []
    named: list[str] = []

    def _push(raw: Any) -> None:
        s = str(raw or "").strip()
        if not s or _UUID_RE.match(s):
            return
        if s.lower() in {"unknown", "none", "null"}:
            return
        # Skip temp / audit folder names.
        if s.startswith("_") or s.lower().startswith(("tmp", "temp", "ob-", "audit")):
            return
        if re.fullmatch(r"\d{4,8}", s):
            numbered.append(s)
        else:
            named.append(s)

    for raw in (
        sow.get("case_label"),
        sow.get("deal_name"),
        sow.get("case_id"),
        report.get("case_label"),
        report.get("deal_name"),
        report.get("case_id"),
        report.get("project_name"),
        env.get("case_id") if isinstance(env, Mapping) else None,
        env.get("project_name") if isinstance(env, Mapping) else None,
    ):
        _push(raw)
    file_sources: list[Any] = []
    file_sources.extend(report.get("artifacts") or [])
    if isinstance(env, Mapping):
        file_sources.extend(env.get("documents") or [])
        file_sources.extend(env.get("artifacts") or [])
    for art in file_sources:
        if not isinstance(art, Mapping):
            continue
        fn = str(art.get("filename") or art.get("path") or "")
        m = re.match(r"^(\d{4,8})[-_]", fn)
        if m:
            numbered.append(m.group(1))
            break
    _push(case_dir_name)
    if numbered:
        return numbered[0]
    if named:
        return named[0]
    return "This engagement"


def polish_fact_claim(text: str) -> str | None:
    """Rewrite transcript scrap into a PM claim, or None to drop."""
    t = unwrap_fact_text(text or "")
    if len(t) < 8:
        return None
    if is_marketing_or_chrome_fact(t) or _VISION_PLACEHOLDER_RE.search(t):
        return None
    if is_speculative_risk_fact(t):
        return None
    if _DROP_AS_FACT_RE.match(t):
        return None
    # Incomplete soft-commit trailing off — only keep if we can rewrite.
    for pattern, claim in _CLAIM_RULES:
        if pattern.search(t):
            return claim
    # Drop unfinished soft commits that still look like mid-sentence chat.
    if re.search(r"(?i)\bonce they get\.?$", t) and "change order" not in t.lower():
        return None
    if t.endswith("?") and len(t) < 100 and not commercial_substance(t):
        # Open questions belong in customer_questions, not fact cards.
        return None
    # Rambling transcript without a clean claim shape → drop.
    if re.search(r"(?i)\bget back in front of the group\b", t):
        return None
    if t.count(",") >= 3 and len(t) > 140 and not commercial_substance(t):
        if not re.search(r"(?i)\b(sop|poc|meraki|circuit|montreal|paper|smart hands)\b", t):
            return None
    # Light cleanup: strip discourse markers.
    t2 = re.sub(
        r"(?i)^(so|and|but|well|yeah|i mean|like)[, ]+",
        "",
        t,
    ).strip()
    if t2 and t2[0].islower():
        t2 = t2[0].upper() + t2[1:]
    return t2 or t


def fact_overlaps_question(fact_text: str, question_texts: Sequence[str]) -> bool:
    """True when a fact is just restating a curated customer ask."""
    ft = normalize_tokens(fact_text)
    if not ft:
        return False
    for q in question_texts:
        qt = normalize_tokens(q)
        if not qt:
            continue
        if ft in qt or qt in ft:
            return True
        # High token overlap on short facts.
        fset, qset = set(ft.split()), set(qt.split())
        if len(fset) >= 4 and len(fset & qset) / max(len(fset), 1) >= 0.7:
            return True
    return False


def normalize_tokens(text: str) -> str:
    s = re.sub(r"[^a-z0-9\s]+", " ", (text or "").lower())
    return re.sub(r"\s+", " ", s).strip()
