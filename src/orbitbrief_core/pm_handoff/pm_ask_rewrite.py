"""Rewrite evidence into sharp, deal-specific PM decision asks.

Rules:
  - Never paste SOW/email prose after a Confirm stem.
  - Never ship naked coverage templates — specialize with evidence or skip.
  - Skip legal/boilerplate / URL / chrome atoms entirely.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

# Email / social chrome — never a quote decision.
_CHROME_RE = re.compile(
    r"(?i)\b(?:"
    r"hope\s+(?:you(?:'re|\s+are)?|my\s+email)|"
    r"great\s+start\s+to\s+the\s+week|"
    r"don'?t\s+hesitate|"
    r"thank\s+you\s+so\s+much|"
    r"looking\s+forward|"
    r"best\s+regards|"
    r"kind\s+regards|"
    r"please\s+advise|"
    r"i\s+hope\s+this\s+(?:email|note)|"
    r"excited\b|"
    r"chat\s+tomorrow|"
    r"draw\s+up\s+a\s+quote|"
    r"could\s+you\s+please\s+draw\s+up|"
    r"awesome\.?\s+appreciate|"
    r"no\s+worries\s+at\s+all|"
    r"wanna\s+hop\s+on\s+call|"
    r"our\s+worlds\s+get\s+busy"
    r")\b"
)

# Legal / commercial boilerplate that is not a field decision.
_BOILERPLATE_RE = re.compile(
    r"(?i)\b(?:"
    r"material\s+breach|"
    r"terminate\s+this\s+(?:sow|agreement)|"
    r"either\s+party\s+may\s+terminate|"
    r"form\s+w-?9|"
    r"indemnif|"
    r"governing\s+law|"
    r"force\s+majeure|"
    r"confidential(?:ity)?\s+obligations?|"
    r"total\s+fees|"
    r"draft\s+intended\s+only|"
    r"review\s+of\s+text|"
    r"knowledgeable\s+resource\s+to\s+complete|"
    r"services\s+not\s+expressly\s+set\s+forth|"
    r"purpose\s+of\s+obtaining\s+credit|"
    r"name\s+of\s+entity/individual|"
    r"entry\s+is\s+required"
    r")\b"
)

_URL_RE = re.compile(
    r"(?i)(?:https?://|www\.|hs-sales-engage|hubspot|urldefense|mimecast|"
    r"ctc/\w+|d\d+-klx\d+)"
)

_DECISION_MARKERS = re.compile(
    r"(?i)\b(?:"
    r"vs\.?|versus|or\b|which|who|what|when|where|how\s+many|"
    r"confirm|clarify|decide|include|exclude|defer|approve|"
    r"in[\-\s]?scope|out\s+of\s+scope|ofe|c[\-\s]?f|owner[\-\s]?furnish|"
    r"keep|remove|reuse|cutover|acceptance|sign[\-\s]?off|"
    r"home\s+run|raceway|in[\-\s]?wall|prewired|by\s+others"
    r")\b"
)

# Modes that are physical install (pathway / AV / wireless templates allowed).
INSTALL_MODES = frozenset(
    {
        "av_install",
        "wireless_install",
        "wireless_config",
        "cabling_install",
        "network_edge_install",
        "access_control",
    }
)
WIRELESS_MODES = frozenset({"wireless_install", "wireless_config", "network_edge_install"})
AV_MODES = frozenset({"av_install"})
SECURITY_MODES = frozenset({"access_control", "security_assessment", "generic"})


def is_chrome_or_boilerplate(text: str) -> bool:
    t = text or ""
    if _CHROME_RE.search(t):
        return True
    if _BOILERPLATE_RE.search(t):
        return True
    if _URL_RE.search(t) and sum(ch.isalnum() for ch in t) < 80:
        return True
    if _URL_RE.search(t) and not _DECISION_MARKERS.search(t):
        return True
    return False


def is_unusable_evidence_text(text: str) -> bool:
    """Hard skip for atoms that must never become questions."""
    t = (text or "").strip()
    if len(t) < 16:
        return True
    if is_chrome_or_boilerplate(t):
        return True
    if t.count("|") >= 3:
        return True
    if re.search(r"(?i)^\s*acceptance\s+criteria\s+device\b", t):
        return True
    if re.search(r"(?i)^\s*>\s*", t) and len(t) < 80:
        return True
    # Casual email / P.S. chatter / scheduling smalltalk
    if re.search(
        r"(?i)(?:"
        r"^\s*p\.?\s*s\.?\b|probably send over|would that work|"
        r"noon\s+eastern|send an invite|move the call|"
        r"rivalry|giants|cubs|ball\s*park the costs|"
        r"verbal today|credit card ok|"
        r"partnership moving forward|"
        r"when you have a minute"
        r")",
        t,
    ):
        return True
    # Truncated mid-phrase
    if re.search(r"(?i)\bwithin\s+\d+\s*hr\s+of\s*$|pattern\s+OPTBOT", t):
        return True
    return False


def _clip_anchor(text: str, n: int = 72) -> str:
    body = re.sub(r"\s+", " ", (text or "").strip())
    body = re.sub(r"^[\-\*\d\.\)\s>]+", "", body)
    body = re.sub(r"[*_`]+", "", body)
    # Never keep URLs in anchors
    body = _URL_RE.sub("", body).strip()
    if len(body) <= n:
        return body.rstrip(".,;:")
    cut = body[: n - 1].rsplit(" ", 1)[0]
    return (cut or body[: n - 1]).rstrip(".,;:")



def _clean_bom_anchor(text: str, n: int = 56) -> str | None:
    """Strip meter/pipe inventory chrome; reject qty-0 and truncated junk."""
    raw = re.sub(r"\s+", " ", (text or "").strip())
    if not raw or _URL_RE.search(raw):
        return None
    if re.search(r"(?i)\|\s*0\s*\|", raw) or re.search(r"(?i)\bquantity\s+0\b", raw):
        return None
    if re.search(r"(?i)\bmeter\s+(?:device|quantity|shipping)\b", raw) and "|" in raw:
        raw = raw.split("|", 1)[0].strip()
    elif "|" in raw:
        raw = raw.split("|", 1)[0].strip()
    raw = re.sub(r"(?i)\bmeter\s+(?:device|quantity|shipping).*$", "", raw).strip()
    raw = re.sub(r"(?i)\bquantity\s+\d+\b.*$", "", raw).strip()
    raw = re.sub(r"(?i)\s*\bqty\s*[:=]?\s*\d+\s*$", "", raw).strip()
    if re.search(
        r"(?i)(?:is all of the\s*$|equipment for pickup|pickup\s*&\s*disposal)",
        raw,
    ):
        return None
    if len(raw) < 12:
        return None
    return _clip_anchor(raw, n)


# Canonical payment ask — rewrite + pmcover must use this exact wording.
PAYMENT_GATE_ASK = (
    "Confirm payment terms (deposit / milestones / Net-X) that gate scheduling."
)


def extract_deal_flavor(blob: str) -> str | None:
    """OEM / SKU / program token that differentiates deals sharing a HQ city."""
    if not blob:
        return None
    patterns = (
        r"\b(Meraki\s+M[RSX]\d+[\w-]*)",
        r"\b(Catalyst\s+9\d{3,5}\w*)",
        r"\b(Cisco\s+CW\d+[\w-]*)",
        r"\b(CW\d{4,5}[\w-]*)",
        r"\b(PowerEdge\s+R\d+\w*)",
        r"\b(Neat\s+(?:Bar|Board|Pad|Frame)\w*)",
        r"\b(Yealink\s+[A-Z0-9-]+)",
        r"\b(Iron\s+Mountain)",
        r"\b(Verkada\s+\w+)",
        r"\b(Aruba\s+(?:AP|IAP)[\w-]*)",
        r"\b(Ruckus\s+[\w-]+)",
        r"\b(?:Omada|UniFi)\s+[\w-]+",
        r"\b(FortiAP[\w-]*)",
        r"\b(Teams\s+Room)",
        r"\b(Zoom\s+Room)",
        r"\b(Google\s+Meet\s+Hardware)",
    )
    for pat in patterns:
        m = re.search(pat, blob, re.I)
        if m:
            return re.sub(r"\s+", " ", m.group(1)).strip()
    # Customer / account label when OEM is absent (breaks Alpharetta HQ clones).
    # Cap at 1–3 Title-Case tokens — never slur prose ("… setup to be").
    m = re.search(
        r"(?i)(?:account|customer|client|company)\s*[:\-]\s*"
        r"([A-Z][A-Za-z0-9&.,']+(?:\s+[A-Z][A-Za-z0-9&.,']+){0,2})",
        blob,
    )
    if m:
        name = re.sub(r"\s+", " ", m.group(1)).strip(" .,")
        if (
            3 <= len(name) <= 28
            and not re.search(
                r"(?i)\b(?:the|inc|llc|for|and|setup|to|be|camera|security)\b",
                name,
            )
        ):
            return name
    return None


def inject_site_anchor(
    ask: str,
    site_names: list[str] | None,
    *,
    blob: str = "",
) -> str:
    """Pin a generic stem to site and/or OEM flavor so cross-deal clones diverge."""
    if not ask:
        return ask
    flavor = extract_deal_flavor(blob)
    site = (site_names[0].strip() if site_names else "") or ""
    generic = bool(
        re.search(
            r"(?i)(?:remote/no-travel|business hours|delivery schedule locked|"
            r"pathway infrastructure|budget ceiling|customer-furnished|"
            r"named engineer \+ contact|ceiling height / access|"
            r"who owns pathway|who signs acceptance|1-for-1 swap|"
            r"paid site survey required|fresh site survey required|"
            r"authoritative AP list|displays?/codecs stay|"
            r"in-scope sites for this wave|access/escort/badging|"
            r"how many aps|ap count/model|new cable pulls|"
            r"pathway method|in-wall fish|day-of onsite contact)",
            ask,
        )
    )
    if not generic:
        return ask
    bits: list[str] = []
    if flavor and flavor.lower() not in ask.lower():
        bits.append(flavor)
    if site and site.lower() not in ask.lower():
        bits.append(f"at {site}")
    elif len(site_names or []) >= 2:
        s2 = site_names[1].strip()
        if s2 and s2.lower() not in ask.lower() and (not site or s2.lower() != site.lower()):
            bits.append(f"incl. {s2}")
    if not bits:
        return ask
    tag = " · ".join(bits)
    if ask.endswith("?"):
        return f"{ask[:-1]} — {tag}?"
    return f"{ask} — {tag}"


def rewrite_instruction(text: str) -> str | None:
    if is_unusable_evidence_text(text):
        return None
    low = text.lower()

    # Kill internal / meta
    if re.search(r"(?i)new\s+thread|who should i include|customer thread", low):
        return None
    if re.search(r"(?i)need to figure|figure this|what open item", low):
        # Only keep if we can name something concrete from the same text
        if not re.search(
            r"(?i)\b(?:ap|cable|hardware|schedule|budget|region|backup|pentest|survey)\b",
            low,
        ):
            return None
    if re.search(r"(?i)operations\s+early", low):
        return None

    rules: list[tuple[str, str]] = [
        (r"home\s+runs?|new\s+pulls?|terminate\s+to\s+existing",
         "For the new APs — new home runs/pulls, or terminate to existing port availability only?"),
        (r"1\s*for\s*1\s*swap|like[\-\s]?for[\-\s]?like|swap\s+the\s+aps?",
         "Is AP work a 1-for-1 swap on existing drops, or do we run new cable?"),
        (r"large\s+room\s+av|smarthands|smart\s+hands",
         "Which rooms are large-room AV (full install) vs smart-hands only?"),
        (r"rebate|gear\s+pickup",
         "Who owns HP/OEM rebate process and gear pickup logistics before rollout?"),
        (r"source\s+hardware|do not have a contact|customer[\-\s]?furnished|ofe",
         "Who sources hardware — customer-furnished (OFE) or PurTera-furnished?"),
        (r"mobilization|conduit\s+pull",
         "Confirm mobilization timing relative to electrician conduit pull."),
        (r"8\s*ft\s*ladder|ladder\s+access|safely\s+accessible",
         "Confirm all AP/device locations are reachable with an 8ft ladder — any lifts or after-hours access needed?"),
        (r"cost per location|per[\-\s]?site",
         "Confirm pricing is per-location as quoted — which sites are in this wave?"),
        (r"addresses?/locations?\s+are\s+different|confirm if these are the correct",
         "Which site address list is authoritative for this quote — customer list or ours?"),
        (r"three\s+oems?|config\s+list|rfp",
         "Which OEM/config from the RFP shortlist is selected for this quote?"),
        (r"cpu|memory|drive\s+space|1\s*tb\s+drives",
         "Confirm target CPU / memory / storage upgrade specs per branch before we quote BOM."),
        (r"single\s+point\s+of\s+contact|\bpoc\b",
         "Who is the single customer point of contact for scheduling and acceptance?"),
        (r"phase\s+two|post[\-\s]?construction|fire\s+marshal|ahj",
         "What is locked in phase-1 quote vs deferred until AHJ/fire-marshal post-construction assessment?"),
        (r"wireless\s+repeaters?",
         "Are wireless repeaters in this quote, allowance, or deferred pending RF survey?"),
        (r"contractual\s+terms|onboarding|choate",
         "Which contractual/onboarding terms must be locked before we schedule mobilization?"),
        (r"3[\-\s]?month\s+window|window\s+for",
         "Confirm the approved engagement window / hard end date for this work."),
        (r"lead\s+time|kick\s+off|once they decide",
         "What is the lead time from customer decision to kickoff, and who releases the schedule?"),
        (r"troubleshoot|structured\s+cabling",
         "Is structured-cabling troubleshooting in-scope for techs, or cable plant is customer/GC owned?"),
        (r"sign and return|move forward with scheduling",
         "Confirm quote signature releases scheduling — any remaining commercial holds?"),
        (r"cat6|plenum",
         "Is CAT6 plenum-rated cable required for the new drops?"),
        (r"scissor\s+lift|boom\s+lift|lift\s+rental",
         "Confirm lift type/qty required — scissor, boom, or ladder-only — and who furnishes the lift?"),
        (r"regular hours or after hours|after[\-\s]?hours",
         "Is the site survey / install regular business hours or after-hours?"),
    ]
    for pat, ask in rules:
        if re.search(pat, low):
            return ask

    clean = re.sub(r"\s+", " ", text).strip()
    clean = re.sub(r"[*_`]+", "", clean)
    if "?" in clean and _DECISION_MARKERS.search(clean):
        clean = clean.split("?", 1)[0].strip() + "?"
        if 24 <= len(clean) <= 140 and not _URL_RE.search(clean) and not is_chrome_or_boilerplate(clean):
            if clean[0].islower():
                clean = clean[0].upper() + clean[1:]
            return clean
    return None


def rewrite_assumption(
    text: str,
    *,
    site_names: list[str] | None = None,
    blob: str = "",
) -> str | None:
    if is_unusable_evidence_text(text):
        return None
    low = text.lower()
    if re.search(r"(?i)^\s*(?:cost|selll?)\s+rates?\s*:", text):
        return None
    if re.search(r"(?i)labor\s+sell\s+rate|usd\s+per\s+hour", text):
        return None

    rules: list[tuple[str, str]] = [
        (r"prewired|already\s+pre-?wired",
         "Confirm pathways are already prewired — or add pull/pathway labor to the quote?"),
        (r"owner\s+furnish|ofe|by\s+others|customer[\-\s]?furnish",
         "Confirm what stays customer-furnished / by-others vs PurTera-furnished on this quote."),
        (r"maximum of\s*\d+\s*technicians|crew\s+constraint|2\s+technicians\s+per\s+site",
         "Confirm crew-size cap still applies — quote overtime / extra techs if a site needs more?"),
        (r"no\s+travel|delivered\s+remotely|travel\s+outside|travel[\-\s]?related\s+expenses",
         "Confirm remote/no-travel delivery — which sites would trigger travel billing if needed?"),
        (r"no\s+design\s+engineering|avoid\s+consultant",
         "Confirm design/engineering is out of scope, or add design hours to the quote?"),
        (r"conduit|sleeves|core\s+drilling|trenching|pull\s+boxes|pathway.*by\s+(?:electrical|others)",
         "Confirm pathway infrastructure (conduit/sleeves/power) remains by others — any PurTera pathway scope?"),
        (r"plywood\s+backboards|grounding\s+systems|120v\s+power\s+by\s+others|electrical\s+work|electrical\s+outlets",
         "Confirm backboards / grounding / 120V power remain by others for every site."),
        (r"exit\s+hardware|electrified\s+door|panic\s+hardware|electric\s+latch",
         "Who furnishes electrified/exit door hardware — customer, GC, or PurTera?"),
        (r"camera\s+locations?\s+are\s+accessible|standard\s+ladders",
         "Confirm all camera locations are ladder-accessible — any lift, roof, or after-hours work?"),
        (r"half\s+hour|rounded\s+up",
         "Confirm T&M rounding (half-hour increments) is accepted on this engagement."),
        (r"delivery\s+schedule|assigns?\s+a\s+project\s+manager",
         "When is the delivery schedule locked, and who is the customer scheduler counterpart?"),
        (r"backup\s+engine|data\s+movement|final\s+technical\s+design",
         "Which backup engine / data-movement method is approved before we finalize design pricing?"),
        (r"third[\-\s]?party\s+legal\s+entity|formal\s+approval",
         "Which third-party entity must approve testing, and what is the approval lead time?"),
        (r"ongoing\s+monitoring|operational\s+ownership",
         "Is ongoing monitoring/support in this quote, or a separate ops agreement?"),
        (r"mfa|conditional\s+access",
         "Confirm MFA / conditional-access assumptions still match the customer’s IdP policy."),
        (r"production\s+transfer|bandwidth|change\s+rate",
         "Confirm production cutover duration assumptions (data size, bandwidth, tooling) — any hard outage window?"),
        (r"fixed\s+fee|baseline\s+fixed",
         "Confirm fixed-fee baseline still holds — what change triggers T&M / change order?"),
        (r"verkada|mounting\s+hardware\s+are\s+provided",
         "Who furnishes cameras/mounting hardware — customer-provided or PurTera BOM?"),
        (r"business\s+hours",
         "Confirm all work stays in normal business hours — any after-hours premium required?"),
        (r"one\s+substantially|punch|closeout",
         "Confirm punch/closeout is one contiguous visit — or quote return trips separately?"),
    ]
    for pat, ask in rules:
        if re.search(pat, low):
            return inject_site_anchor(ask, site_names, blob=blob)
    # No generic quote-paste fallback.
    return None


# Modes where assessment / cloud / pentest asks are legitimate.
_ASSESSMENT_OK_MODES = frozenset({"security_assessment", "generic", "alm"})
_INSTALL_ONLY_MODES = frozenset(
    {
        "av_install",
        "wireless_install",
        "wireless_config",
        "cabling_install",
        "network_edge_install",
    }
)


def rewrite_scope(
    text: str,
    atom_type: str = "scope_item",
    *,
    project_mode: str = "",
    site_names: list[str] | None = None,
    blob: str = "",
) -> str | None:
    if is_unusable_evidence_text(text):
        return None
    low = text.lower()
    mode = (project_mode or "").strip()
    # Methodology essays / marketing / legal fee language — skip
    if re.search(
        r"(?i)\b(?:aims to evaluate|methodology for conducting|highest priority on the security|"
        r"internationally recognize|owasp top 10|cvss\b|total\s+fees|draft\s+intended|"
        r"knowledgeable\s+resource|services\s+expressly)\b",
        text,
    ):
        return None

    # Assessment / cloud asks — never on physical install modes.
    if mode in _INSTALL_ONLY_MODES and re.search(
        r"(?i)\b(?:pentest|penetration\s+test|assessment\s+report|executive\s+summary|"
        r"azure\s+(?:ad|backup|region)|entra|immutable\s+storage|white\s+box|"
        r"rules?\s+of\s+engagement)\b",
        low,
    ):
        return None
    # Staff-aug wording must not leak onto wireless/AV installs.
    if mode in _INSTALL_ONLY_MODES | WIRELESS_MODES | AV_MODES and re.search(
        r"(?i)staff\s+augmentation",
        low,
    ):
        return None

    rules: list[tuple[str, str]] = []
    # Decommission asks only on decom mode or when the atom itself is pack-out evidence.
    decom_atom = bool(
        re.search(
            r"(?i)\b(?:iron\s+mountain|de[\-\s]?rack|pack(?:ing)?\s*/?\s*prep|"
            r"palletize|return\s+shipping|equipment for (?:pickup|disposal))\b",
            low,
        )
    )
    if mode == "decommission_logistics" or decom_atom:
        rules.extend(
            [
                (r"iron\s+mountain|de[\-\s]?rack|pack(?:ing)?\s*/?\s*prep|palletize|shrink\s+wrap",
                 "Confirm decommission scope — derack/pack/ship vs inventory-only — and who owns packing materials?"),
                (r"return\s+shipping|box\s+shipping|serviot\s+to\s+pack",
                 "Who packs and ships returns — PurTera/Serviot pack-leave-onsite, or customer-arranged carrier?"),
                (r"visit\s*1|onsite\s+inventory\s+verification",
                 "Confirm Visit-1 inventory vs Visit-2 pack/ship are separate mobilizations in this quote."),
                (r"power\s+down\s+equipment|bring\s+down\s+network",
                 "Who owns equipment power-down / network take-down before pack-out — customer or PurTera?"),
                (r"dress\s+code|background\s+check",
                 "Confirm background-check / dress-code requirements before scheduling onsite crew."),
                (r"racked\s+servers|boxed\s+servers|pre[\-\s]?boxed",
                 "Which sites are racked-server derack vs already-boxed pickup — lock per site before dispatch?"),
                (r"hours of operation for the dock|loading\s+dock",
                 "Confirm dock hours / appointment lead time for each pickup site."),
                (r"additional charge|packing materials will be provided",
                 "Confirm packing-materials fee is in this quote, allowance, or customer-furnished?"),
                (r"equipment for pickup|equipment for disposal|misc\.?\s*\(.*cables",
                 "Confirm pickup/disposal inventory list is authoritative — any exclusions before crew arrives?"),
            ]
        )
    rules.extend(
        [
        (r"poweredge|r840|raid\s+controller|xeon\s+gold",
         "Confirm which PowerEdge nodes / RAID / CPU configs are in this quote wave."),
        (r"exact\s+urls?\s+for\s+the\s+applications?",
         "What are the exact application URLs / environments in scope for testing?"),
        (r"immutable\s+storage|worm|blob\s+versioning",
         "Confirm immutable/WORM/versioning requirements that must be designed into this quote."),
        (r"configure\s+azure\s+backup|backup\s+vault",
         "Is Azure Backup vault configuration in this quote’s fixed scope?"),
        (r"penetration\s+test|pentest|manual\s+testing",
         "Confirm pentest type (black/grey/white box), environments, and out-of-scope systems."),
        (r"executive\s+summary|assessment\s+report",
         "Which report deliverables are in the fixed fee (exec summary, full findings, retest)?"),
        (r"engineer\s+name\s+and\s+contact",
         "Confirm we must provide named engineer + contact before kickoff — any clearance constraints?"),
        (r"white\s+box|snippets?\s+of\s+code",
         "Will customer provide code/snippets for white-box validation, or stay black/grey-box only?"),
        (r"four\s*\(\s*4\s*\)\s*weeks|implementation\s+time",
         "Confirm the quoted duration still matches customer need-by date."),
        (r"target\s+region|azure\s+regions?",
         "Which Azure regions (primary/secondary) are approved for this design?"),
        # Budget only when a concrete ceiling / $ figure is present — not every "budget" mention.
        (r"(?:budget|run[\-\s]?rate|ceiling).{0,40}(?:\$|usd|\d[\d,]*(?:\.\d+)?\s*k\b|\d{3,})",
         "What is the budget ceiling we must design/quote to?"),
        (r"lrs|zrs|grs|ra[\-\s]?grs|redundancy",
         "Which storage redundancy option is required (LRS / ZRS / GRS / RA-GRS)?"),
        (r"retention\s+policy|data\s+classification",
         "Is retention uniform across the dataset, or tiered by classification — what are the tiers?"),
        (r"prove\s+that\s+protected\s+data\s+cannot\s+be\s+deleted",
         "What acceptance test proves immutability / undeletable protected data?"),
        (r"like\s+for\s+like\s+swaps?",
         "Confirm AP replacements are like-for-like swaps on existing mounts/drops only."),
        (r"extensive\s+tracing|new\s+cable",
         "If cabling needs extensive tracing or new pulls, is that T&M / change-order or out of scope?"),
        (r"troubleshoot.*structured\s+cabling|minor\s+structured\s+cabling",
         "Is structured-cabling troubleshooting in-scope for techs, or cable plant is customer/GC owned?"),
        (r"accurate\s+ap\s+list|location\s+map|floor\s+plan",
         "Who provides the authoritative AP list / floor plan before mobilization?"),
        (r"no\s+structured\s+cabling|wi[\-\s]?fi[\-\s]?only",
         "Confirm no structured cabling is in scope — Wi-Fi-only seats as documented?"),
        (r"weekly\s+status|wave\s+closeout",
         "Confirm weekly status + wave closeout reporting is included in the fixed fee."),
        (r"no\s+lift|ladder\s+truck|scaffolding",
         "Confirm install is ladder-only — no lift/scaffolding rental in the quote?"),
        (r"lower\s+\d+\s+existing\s+access\s+points|existing\s+access\s+points",
         "Confirm which existing APs are lowered/reused vs replaced, and who owns the old gear."),
        (r"access\s+to\s+all\s+tanks|tanks\s+included",
         "Confirm customer provides tank/work-area access for every site visit."),
        (r"hostname\s+pattern|intune\s+compliant|enrolled\s+devices",
         "Confirm device compliance / hostname standards are in-scope acceptance criteria for this quote."),
        (r"telemetry|anova|sap\s+s4",
         "Confirm which telemetry / SAP dependencies are in-scope vs customer-owned for go-live."),
        (r"google\s+meet\s+hardware|meet\s+hardware",
         "Confirm Google Meet hardware labor/equipment lines are in this quote as written."),
        (r"imac|workstation\s+count|device\s+count",
         "Where workstation/iMac counts disagree across sources, which quantity is authoritative?"),
        (r"ceiling\s+height|need a lift|ladder is",
         "Confirm ceiling height / access method — ladder-only or lift required?"),
        (r"space in the rack|rack for the network",
         "Confirm rack space is available for the new network devices at this site."),
        (r"send someone over first|site survey|take a look at the",
         "Is a paid site survey required before final quote, or is prior walkthrough sufficient?"),
        (r"cisco\s+ap|status at this point",
         "Confirm existing Cisco AP status — reuse mounts/drops, or full rip-and-replace?"),
        (r"staff\s+augmentation|installation and configuration",
         "Confirm staff-aug scope: install-only, config-only, or install+config+documentation?"),
        (r"already sent someone|paid his hours",
         "Confirm prior site-visit hours are sunk — do not re-bill survey, or re-quote a fresh survey?"),
        ]
    )
    for pat, ask in rules:
        if re.search(pat, low):
            # Extra mode gate for assessment-flavored asks
            if mode and mode not in _ASSESSMENT_OK_MODES and re.search(
                r"(?i)pentest|assessment report|azure region|immutable|white-box|report deliverable",
                ask,
            ):
                continue
            if mode in _INSTALL_ONLY_MODES and re.search(r"(?i)staff-aug scope", ask):
                continue
            return inject_site_anchor(ask, site_names, blob=blob)

    # No quote-wrap fallback. If we cannot name a real decision, skip.
    return None


def rewrite_requirement(text: str, atom_type: str) -> str | None:
    if is_unusable_evidence_text(text):
        return None
    low = text.lower()
    clean = re.sub(r"\s+", " ", text).strip()
    clean = re.sub(r"[*_`]+", "", clean)
    if clean.startswith("-") or clean.startswith(">"):
        clean = clean.lstrip("-> ").strip()

    # Keep already-clean questions (single interrogative only).
    if "?" in clean and not _URL_RE.search(clean):
        clean = clean.split("?", 1)[0].strip() + "?"
        if 24 <= len(clean) <= 160:
            if clean[0].islower():
                clean = clean[0].upper() + clean[1:]
            if not is_chrome_or_boilerplate(clean):
                return clean

    if atom_type == "exclusion":
        # Only sharp exclusions with install/commercial meaning
        if re.search(
            r"(?i)\b(?:power|conduit|drywall|patch|paint|ofe|by\s+others|permit|"
            r"electrical|lift|travel|cabling|design)\b",
            low,
        ):
            if re.search(r"(?i)any\s+services\s+not\s+expressly", low):
                return None
            anchor = _clip_anchor(text, 56)
            if len(anchor) < 20:
                return None
            return f"Confirm exclusion stands: \"{anchor}\" remains customer/GC-owned?"
        return None

    if atom_type == "acceptance_criterion":
        if re.search(r"(?i)acceptance\s+criteria\s+device", low):
            return None
        if re.search(r"(?i)cannot\s+be\s+deleted|undeletable|immutab", low):
            return "What acceptance test proves protected data cannot be deleted or overwritten?"
        return None

    if atom_type in {"payment_term", "contract_term", "change_order_rule"}:
        if re.search(r"(?i)50%|deposit|net\s*\d+|invoice", text):
            return PAYMENT_GATE_ASK
        if re.search(r"(?i)change\s+order", text):
            return "What change-order threshold and approval path apply before we proceed with extras?"
        return None

    # Prefer specific rewrites over binding-wrap
    scoped = rewrite_scope(text, "requirement")
    if scoped:
        return scoped

    rules: list[tuple[str, str]] = [
        (r"escort\s+lead\s+times|badging",
         "Confirm escort lead times and badging requirements per site before scheduling."),
        (r"cat6|plenum",
         "Is CAT6 plenum-rated cable required for the new drops?"),
        (r"emt\s+conduit|flexible\s+conduit|threaded\s+rod|strut",
         "Which pathway materials are in PurTera scope — EMT, flex, strut/rod — or by others?"),
        (r"scissor\s+lift|boom\s+lift|ladder",
         "Confirm access method — scissor lift, boom, or ladder — and who furnishes it?"),
        (r"regular hours or after hours",
         "Is the site survey / install regular business hours or after-hours?"),
        (r"lift\s+rental\s+at\s+\d+",
         "Confirm lift rental qty in the quote matches field need."),
        (r"multiple\s+user\s+accounts",
         "How many test user accounts (roles) must customer provision before pentest kickoff?"),
        (r"hard\s+deadlines?|milestones?",
         "What hard deadlines / milestones must the quote schedule hit?"),
        (r"regulatory\s+frameworks?|compliance\s+drivers?",
         "Which regulatory frameworks drive scope (and any out-of-scope systems)?"),
        (r"uat|production|environment\s+to\s+be\s+tested",
         "Which environments are in scope for testing (UAT / Production / other)?"),
        (r"single\s+point\s+of\s+contact",
         "Who is the single customer point of contact for scheduling and acceptance?"),
        (r"network\s+remediation|switch\s+configuration|firewall|vlan",
         "Is network remediation (switch/firewall/VLAN) in this quote or customer-owned?"),
        (r"wireless\s+credentials|ethernet",
         "Who provides network access info / wireless credentials before mobilization?"),
        (r"no\s+lift|scaffolding",
         "Confirm install is ladder-only — no lift/scaffolding rental in the quote?"),
        (r"tanks?\s+and\s+surrounding",
         "Confirm customer provides tank/work-area access for every site visit."),
    ]
    for pat, ask in rules:
        if re.search(pat, low):
            return ask
    return None


def rewrite_risk(text: str) -> str | None:
    if is_unusable_evidence_text(text):
        return None
    if len(text) < 40:
        return None
    if re.search(r"(?i)ip\s+add(?:ress)?|blocking|security\s+mechanism\s+prevents", text):
        return "If customer security controls block testing, who approves allow-listing and within what SLA?"
    if re.search(r"(?i)patch\s+management|delayed.*updates", text):
        return "Is patching/remediation of findings in-scope, or findings-only with customer-owned remediation?"
    if re.search(r"(?i)exploitation|sensitive\s+data", text):
        return "Confirm rules of engagement for exploitation attempts and sensitive-data handling during the test."
    # No generic risk wrap.
    return None


def rewrite_bom(text: str) -> str | None:
    if is_unusable_evidence_text(text):
        return None
    if re.search(r"(?i)\btbd\b|allowance|optional|alternate|or\s+equal|nic\b", text):
        anchor = _clean_bom_anchor(text, 56)
        if not anchor or len(anchor) < 16:
            return None
        return f"Lock BOM for \"{anchor}\" — include as written, allowance, or remove?"
    if re.search(r"(?i)\b(?:qty|quantity)\b\s*[:=]?\s*\d+|\d+\s*x\b", text):
        anchor = _clean_bom_anchor(text, 56)
        if not anchor or len(anchor) < 16:
            return None
        return f"Confirm qty/model for \"{anchor}\" is the authoritative quote line?"
    return None


def extract_site_names(blob: str, sites: Iterable[Any] | None = None, limit: int = 3) -> list[str]:
    names: list[str] = []
    if sites:
        for s in sites:
            name = ""
            if isinstance(s, Mapping):
                name = str(s.get("name") or s.get("label") or "").strip()
            else:
                for attr in ("name", "label"):
                    v = getattr(s, attr, None)
                    if isinstance(v, str) and v.strip():
                        name = v.strip()
                        break
            if name and name.lower() not in {n.lower() for n in names}:
                names.append(name)
            if len(names) >= limit:
                return names
    # Fallback: city/state-ish tokens from blob
    for m in re.finditer(
        r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\s*,\s*([A-Z]{2})\b",
        blob or "",
    ):
        label = f"{m.group(1)} {m.group(2)}"
        if label.lower() not in {n.lower() for n in names}:
            names.append(label)
        if len(names) >= limit:
            break
    return names


def specialize_coverage_question(
    suffix: str,
    *,
    blob: str,
    project_mode: str,
    site_names: list[str],
) -> str | None:
    """Return a deal-specific coverage ask, or None to suppress the template."""
    hay = blob or ""
    sites = site_names[:3]
    site_bit = ", ".join(sites) if sites else ""

    # Mode hard-gates
    if suffix == "wireless_design":
        # Hard mode gate — AV/access/assessment deals must not get AP/SSID templates
        # unless project_mode is wireless (evidence alone is not enough; many AV SOWs mention Wi-Fi).
        if project_mode not in WIRELESS_MODES | {"network_edge_install", "cabling_install"}:
            return None
        if not re.search(r"(?i)\b(?:access\s+points?|\baps?\b|ssid|heatmap|rf\s+survey)\b", hay):
            return None
        # Reject zip/phone tails ("91641 APs" → false 41) via lookbehind.
        n_ap = re.search(
            r"(?i)(?<!\d)([1-9]\d{0,2})\s*(?:x\s*)?(?:aps?|access\s+points?)\b",
            hay,
        )
        if n_ap and int(n_ap.group(1)) <= 500:
            return (
                f"Confirm AP count/model for this quote — source mentions {n_ap.group(1)} APs; "
                f"lock model + whether RF survey is in-scope."
            )
        return inject_site_anchor(
            "Confirm AP count/model and whether a predictive/RF survey is in-scope for this quote.",
            sites,
            blob=hay,
        )

    if suffix == "av_keep_remove":
        if project_mode not in AV_MODES and not re.search(
            r"(?i)\b(?:teams\s+room|zoom\s+room|hdmi\s+replicator|codec|display\s+mount)\b", hay
        ):
            return None
        if not re.search(r"(?i)\b(?:display|tv\b|codec|hdmi)\b", hay):
            return None
        return inject_site_anchor(
            "Which existing displays/codecs stay mounted, which are removed, "
            "and what is reused vs new BOM on this site?",
            sites, blob=hay,
        )

    if suffix == "pathway_ownership":
        if project_mode not in INSTALL_MODES and not re.search(
            r"(?i)\b(?:conduit|raceway|in[\-\s]?wall|drywall|cable\s+pull|sleeve)\b", hay
        ):
            return None
        return inject_site_anchor(
            "Who owns pathway (conduit, sleeves, fish, raceway, drywall patch) "
            "on this project — PurTera, GC, or customer?",
            sites, blob=hay,
        )

    if suffix == "security_roe":
        if not re.search(r"(?i)\b(?:penetrat|pentest|vulnerab|red\s+team|allow[\-\s]?list)\b", hay):
            return None
        return (
            "Confirm rules of engagement: environments, time windows, allow-lists, "
            "and emergency stop contacts."
        )

    if suffix == "qty_lock":
        # Only when there is an actual disagreement signal — never "every device"
        if not re.search(
            r"(?i)(?:qty|quantity).{0,40}(?:disagree|mismatch|conflict|differ|vs\.?|versus)|"
            r"(?:bom|quote|email|sow).{0,40}(?:says|shows)\s+\d+",
            hay,
        ):
            return None
        return (
            "Where quantity sources disagree, which document is authoritative "
            "(BOM vs email vs SOW) for this quote?"
        )

    if suffix == "site_list_lock":
        # Need multiple sites or an address-conflict signal
        multi = len(sites) >= 2 or bool(
            re.search(r"(?i)\b(?:sites?|locations?|branches?|stores?)\b.*\b(?:\d+|list|wave)\b", hay)
        )
        addr_conflict = bool(
            re.search(r"(?i)addresses?/locations?\s+are\s+different|confirm if these are the correct", hay)
        )
        if not multi and not addr_conflict:
            return None
        if site_bit:
            ask = (
                f"Confirm in-scope sites for this wave ({site_bit}"
                f"{'…' if len(sites) >= 3 else ''}) — any deferrals?"
            )
        else:
            ask = "Which sites/addresses are in this quote wave, and which are deferred?"
        return inject_site_anchor(ask, sites, blob=hay)

    if suffix == "onsite_contact":
        if project_mode not in INSTALL_MODES and not re.search(
            r"(?i)\b(?:on[\-\s]?site|site\s+lead|escort|facilities\s+contact)\b", hay
        ):
            return None
        if site_bit:
            ask = f"Who is the day-of onsite contact for {sites[0]}, and how do we reach them?"
        else:
            ask = "Who is the day-of onsite contact, and how do we reach them?"
        return inject_site_anchor(ask, sites, blob=hay)

    if suffix == "access_badging":
        if not re.search(
            r"(?i)\b(?:escort|badg(?:e|ing)|after[\-\s]?hours|loading\s+dock|tsa|clearance)\b",
            hay,
        ):
            # Generic "access" alone is too weak
            if project_mode not in INSTALL_MODES:
                return None
        if site_bit:
            ask = (
                f"Confirm access/escort/badging/after-hours requirements for {sites[0]}"
                f"{' and other in-scope sites' if len(sites) > 1 else ''}."
            )
        else:
            ask = "Confirm site access, escort, badging, and after-hours requirements."
        return inject_site_anchor(ask, sites, blob=hay)

    if suffix == "hardware_furnish":
        if not re.search(
            r"(?i)\b(?:ofe|owner[\-\s]?furnish|customer[\-\s]?furnish|by\s+others|bom|hardware)\b",
            hay,
        ):
            return None
        ask = "What hardware is customer-furnished vs PurTera-furnished — and who stages it to site?"
        return inject_site_anchor(ask, sites, blob=hay)

    if suffix == "acceptance":
        if not re.search(r"(?i)\b(?:acceptance|sign[\-\s]?off|poc|sop|commission|uat)\b", hay):
            return None
        return inject_site_anchor(
            "Who signs acceptance, and what is the pass/fail checklist before we invoice?",
            sites, blob=hay,
        )

    if suffix == "payment_gate":
        if not re.search(r"(?i)\b(?:deposit|50\s*%|net\s*\d+|purchase\s+order|\bpo\b)\b", hay):
            return None
        return PAYMENT_GATE_ASK

    if suffix == "change_order":
        if not re.search(r"(?i)\b(?:change\s+order|t\s*&\s*m|time\s+and\s+materials)\b", hay):
            return None
        return "What change-order path applies when field conditions differ from quote assumptions?"

    if suffix == "work_hours":
        if not re.search(
            r"(?i)\b(?:after[\-\s]?hours|maintenance\s+window|cutover|blackout|business\s+hours)\b",
            hay,
        ):
            return None
        return "What are the approved work hours / blackout windows for install and cutover?"

    if suffix == "first_site":
        if not re.search(r"(?i)\b(?:first\s+site|pilot|phase\s*1|rollout\s+sequence)\b", hay):
            return None
        if site_bit:
            return (
                f"Is {sites[0]} the first site, or name the pilot — "
                f"and what readiness gate starts mobilization?"
            )
        return "Which site is first, and what readiness gate starts mobilization?"

    if suffix == "exclusions":
        # Only with concrete exclusion language, not laundry list
        m = re.search(
            r"(?i)((?:exclud(?:e|ed|es|ing)|not\s+included|by\s+others)[^.!]{10,80})",
            hay,
        )
        if not m:
            return None
        anchor = _clip_anchor(m.group(1), 70)
        if len(anchor) < 20 or is_chrome_or_boilerplate(anchor):
            return None
        return f"Confirm this exclusion is acknowledged: \"{anchor}\"?"

    return None


# Family keys for cross-ask dedupe (one per family in shortlist/pool head).
FAMILY_PREFIXES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("furnish", ("pmcover.hardware_furnish",)),
    ("pathway", ("pmcover.pathway_ownership", "mode.av_install.cable", "mode.av_install.floor")),
    ("access", ("pmcover.access_badging", "site.", "pmcover.onsite_contact")),
    ("sites", ("pmcover.site_list_lock", "pmcover.first_site")),
    ("acceptance", ("pmcover.acceptance",)),
    ("payment", ("pmcover.payment_gate",)),
    ("wireless", ("pmcover.wireless_design", "mode.wireless")),
    ("av", ("pmcover.av_keep_remove", "mode.av_install")),
    ("qty", ("pmcover.qty_lock", "qty.")),
    ("hours", ("pmcover.work_hours",)),
)

# Text-intent families — collapse paraphrase stems even when rule_ids differ.
_TEXT_FAMILIES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("payment", re.compile(r"(?i)payment terms.*(?:gate scheduling|deposit)")),
    ("travel", re.compile(r"(?i)remote/no-travel|travel billing if needed")),
    ("hours", re.compile(r"(?i)business hours|after-hours premium|work hours / blackout")),
    ("schedule", re.compile(r"(?i)delivery schedule locked|customer scheduler counterpart")),
    ("budget", re.compile(r"(?i)budget ceiling we must design")),
    ("pathway", re.compile(
        r"(?i)pathway (?:method|infrastructure|ownership)|in-wall fish vs surface raceway|"
        r"conduit/sleeves/power"
    )),
    ("furnish", re.compile(r"(?i)customer-furnished|purtera-furnished|who stages it to site")),
    ("cable_vs_swap", re.compile(r"(?i)1-for-1 swap|new cable pulls|run cable for the ap")),
    ("engineer_name", re.compile(r"(?i)named engineer \+ contact")),
    ("survey", re.compile(r"(?i)paid site survey required|prior walkthrough sufficient")),
    ("av_keep", re.compile(r"(?i)displays?/codecs stay|tvs?/displays stay mounted")),
    ("ceiling", re.compile(r"(?i)ceiling height / access method")),
    ("pathway_own", re.compile(r"(?i)who owns pathway")),
    ("acceptance", re.compile(r"(?i)who signs acceptance")),
    ("ap_list", re.compile(r"(?i)authoritative AP list / floor plan")),
)


def family_key_for_rule(rule_id: str) -> str | None:
    rid = rule_id or ""
    for fam, prefixes in FAMILY_PREFIXES:
        if any(rid.startswith(p) or p in rid for p in prefixes):
            if fam == "furnish" and not rid.startswith("pmcover.hardware_furnish"):
                continue
            if fam == "access" and rid.startswith("site.") and "access" not in rid and "escort" not in rid and "onsite" not in rid:
                continue
            return fam
    if rid.startswith("pmcover."):
        return rid.split(".", 1)[-1]
    return None


def family_key_for_question(text: str, rule_id: str = "") -> str | None:
    """Prefer text-intent family so payment/pathway paraphrases collapse."""
    t = text or ""
    for fam, pat in _TEXT_FAMILIES:
        if pat.search(t):
            return fam
    return family_key_for_rule(rule_id)
