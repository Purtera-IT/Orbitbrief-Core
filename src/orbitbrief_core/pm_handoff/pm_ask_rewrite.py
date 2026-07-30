"""Rewrite evidence blobs into sharp PM decision asks.

Never paste SOW/email prose after a Confirm stem. Either extract a real
choice the PM must lock, or skip the atom.
"""
from __future__ import annotations

import re
from typing import Any

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
    r"could\s+you\s+please\s+draw\s+up"
    r")\b"
)

# Legal/commercial boilerplate that is not a field decision.
_BOILERPLATE_RE = re.compile(
    r"(?i)\b(?:"
    r"material\s+breach|"
    r"terminate\s+this\s+(?:sow|agreement)|"
    r"either\s+party\s+may\s+terminate|"
    r"form\s+w-?9|"
    r"indemnif|"
    r"governing\s+law|"
    r"force\s+majeure|"
    r"confidential(?:ity)?\s+obligations?"
    r")\b"
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


def is_chrome_or_boilerplate(text: str) -> bool:
    t = text or ""
    if _CHROME_RE.search(t):
        return True
    if _BOILERPLATE_RE.search(t):
        return True
    return False


def _clip_anchor(text: str, n: int = 72) -> str:
    body = re.sub(r"\s+", " ", (text or "").strip())
    body = re.sub(r"^[\-\*\d\.\)\s]+", "", body)
    if len(body) <= n:
        return body
    cut = body[: n - 1].rsplit(" ", 1)[0]
    return (cut or body[: n - 1]).rstrip(".,;:") + "…"


def rewrite_instruction(text: str) -> str | None:
    """Customer note → sharp PM ask. None = skip."""
    if not text or len(text.strip()) < 16:
        return None
    if is_chrome_or_boilerplate(text):
        return None
    low = text.lower()

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
        (r"operations\s+early",
         "Confirm operations must be involved early for equipment decisions and install logistics."),
        (r"mobilization|conduit\s+pull",
         "Confirm mobilization timing relative to electrician conduit pull."),
        (r"need to figure|figure this|still open|not sure",
         "What open item still needs a customer decision before we can lock the quote?"),
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
        (r"single\s+point\s+of\s+contact|poc\b",
         "Who is the single customer point of contact for scheduling and acceptance?"),
        (r"phase\s+two|post[\-\s]?construction|fire\s+marshal|ahj",
         "What is locked in phase-1 quote vs deferred until AHJ/fire-marshal post-construction assessment?"),
        (r"wireless\s+repeaters?",
         "Are wireless repeaters in this quote, allowance, or deferred pending RF survey?"),
        (r"contractual\s+terms|onboarding|choate",
         "Which contractual/onboarding terms must be locked before we schedule mobilization?"),
        (r"3[\-\s]?month\s+window|window\s+for",
         "Confirm the approved engagement window / hard end date for this work."),
        (r"new\s+thread|who should i include",
         "Who must be on the customer thread for scope decisions (names/roles)?"),
        (r"lead\s+time|kick\s+off|once they decide",
         "What is the lead time from customer decision to kickoff, and who releases the schedule?"),
        (r"only take a few days|set expectations",
         "Confirm customer schedule expectation (days vs weeks) against our install duration — who resets expectations?"),
        (r"troubleshoot|structured\s+cabling",
         "Is structured-cabling troubleshooting in-scope for techs, or cable plant is customer/GC owned?"),
        (r"sign and return|move forward with scheduling",
         "Confirm quote signature releases scheduling — any remaining commercial holds?"),
    ]
    for pat, ask in rules:
        if re.search(pat, low):
            return ask

    # Already a clean question from the customer — keep if decision-shaped.
    clean = re.sub(r"\s+", " ", text).strip()
    if "?" in clean and len(clean) <= 140 and _DECISION_MARKERS.search(clean):
        if clean[0].islower():
            clean = clean[0].upper() + clean[1:]
        return clean[:180]
    return None


def rewrite_assumption(text: str) -> str | None:
    if not text or is_chrome_or_boilerplate(text):
        return None
    low = text.lower()
    if re.search(r"(?i)^\s*(?:cost|selll?)\s+rates?\s*:", text):
        return None
    if re.search(r"(?i)labor\s+sell\s+rate|usd\s+per\s+hour", text):
        return None

    rules: list[tuple[str, str]] = [
        (r"prewired|already\s+pre-?wired",
         "Confirm pathways are already prewired — or add pull/pathway labor to the quote?"),
        (r"owner\s+furnish|ofe|by\s+others|customer[\-\s]?furnished",
         "Confirm what stays customer-furnished / by-others vs PurTera-furnished on this quote."),
        (r"maximum of\s*\d+\s*technicians|crew\s+constraint|2\s+technicians\s+per\s+site",
         "Confirm crew-size cap still applies — quote overtime / extra techs if a site needs more?"),
        (r"no\s+travel|delivered\s+remotely|travel\s+outside",
         "Confirm remote/no-travel delivery — which sites would trigger travel billing if needed?"),
        (r"no\s+design\s+engineering|avoid\s+consultant",
         "Confirm design/engineering is out of scope, or add design hours to the quote?"),
        (r"conduit|sleeves|core\s+drilling|trenching|pull\s+boxes|pathway.*by\s+(?:electrical|others)",
         "Confirm pathway infrastructure (conduit/sleeves/power) remains by others — any PurTera pathway scope?"),
        (r"plywood\s+backboards|grounding\s+systems|120v\s+power\s+by\s+others",
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
    ]
    for pat, ask in rules:
        if re.search(pat, low):
            return ask

    # Generic but sharp: short anchor, force include/exclude decision.
    if len(text) >= 40 and _DECISION_MARKERS.search(text):
        anchor = _clip_anchor(text, 64)
        return f"Confirm this pricing/scope assumption still stands: \"{anchor}\" — in quote as written, or revise?"
    return None


def rewrite_scope(text: str, atom_type: str = "scope_item") -> str | None:
    if not text or is_chrome_or_boilerplate(text):
        return None
    low = text.lower()
    # Methodology essays / marketing — skip unless a concrete deliverable noun.
    if re.search(
        r"(?i)\b(?:aims to evaluate|methodology for conducting|highest priority on the security|"
        r"internationally recognize|owasp top 10|cvss\b)\b",
        text,
    ) and not re.search(r"(?i)\b(?:deliver|provide|include|configure|install|deploy)\b", text):
        return None

    rules: list[tuple[str, str]] = [
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
        (r"budget|run[\-\s]?rate|ceiling",
         "What is the budget ceiling we must design/quote to?"),
        (r"lrs|zrs|grs|ra[\-\s]?grs|redundancy",
         "Which storage redundancy option is required (LRS / ZRS / GRS / RA-GRS)?"),
        (r"retention\s+policy|data\s+classification",
         "Is retention uniform across the dataset, or tiered by classification — what are the tiers?"),
        (r"prove\s+that\s+protected\s+data\s+cannot\s+be\s+deleted",
         "What acceptance test proves immutability / undeletable protected data?"),
    ]
    for pat, ask in rules:
        if re.search(pat, low):
            return ask

    # Concrete verb + object → include/exclude ask with short anchor.
    if re.search(
        r"(?i)\b(?:install|configure|deploy|provide|deliver|include|migrate|replace|"
        r"upgrade|remove|mount|pull|terminate|commission)\b",
        text,
    ):
        anchor = _clip_anchor(text, 70)
        if atom_type == "deliverable":
            return f"Is this deliverable in the fixed quote: \"{anchor}\"?"
        if atom_type == "task":
            return f"Is this task in-scope for this engagement: \"{anchor}\"?"
        return f"Include in this quote, or exclude: \"{anchor}\"?"
    return None


def rewrite_requirement(text: str, atom_type: str) -> str | None:
    if not text or is_chrome_or_boilerplate(text):
        return None
    low = text.lower()
    # Prefer keeping questions that are already decision-shaped.
    clean = re.sub(r"\s+", " ", text).strip()
    if clean.startswith("-"):
        clean = clean.lstrip("- ").strip()
    if "?" in clean and 20 <= len(clean) <= 160:
        if clean[0].islower():
            clean = clean[0].upper() + clean[1:]
        return clean

    if atom_type == "exclusion":
        anchor = _clip_anchor(text, 70)
        return f"Confirm this stays excluded from PurTera scope: \"{anchor}\"?"
    if atom_type == "acceptance_criterion":
        anchor = _clip_anchor(text, 70)
        return f"What is the pass/fail acceptance test for: \"{anchor}\"?"
    if atom_type in {"payment_term", "contract_term", "change_order_rule"}:
        if re.search(r"(?i)50%|deposit|net\s*\d+|invoice", text):
            return "Confirm payment terms (deposit / milestones / Net-X) that gate scheduling."
        if re.search(r"(?i)change\s+order", text):
            return "What change-order threshold and approval path apply before we proceed with extras?"
        return None
    if re.search(r"(?i)region|azure|storage|backup|retention|redundancy|budget", low):
        return rewrite_scope(text, "requirement")
    anchor = _clip_anchor(text, 70)
    if len(anchor) < 20:
        return None
    return f"Is this a binding requirement for the quote: \"{anchor}\"?"


def rewrite_risk(text: str) -> str | None:
    if not text or is_chrome_or_boilerplate(text):
        return None
    if len(text) < 40:
        return None
    low = text.lower()
    if re.search(r"(?i)ip\s+add(?:ress)?|blocking|security\s+mechanism\s+prevents", text):
        return "If customer security controls block testing, who approves allow-listing and within what SLA?"
    if re.search(r"(?i)patch\s+management|delayed.*updates", text):
        return "Is patching/remediation of findings in-scope, or findings-only with customer-owned remediation?"
    if re.search(r"(?i)exploitation|sensitive\s+data", text):
        return "Confirm rules of engagement for exploitation attempts and sensitive-data handling during the test."
    # Skip bare OWASP category labels
    if len(text) < 60 and not re.search(r"[.]", text):
        return None
    anchor = _clip_anchor(text, 64)
    return f"How should the quote treat this risk — mitigate in-scope, customer-owned, or acceptance caveat: \"{anchor}\"?"


def rewrite_bom(text: str) -> str | None:
    if not text or is_chrome_or_boilerplate(text):
        return None
    low = text.lower()
    if re.search(r"(?i)\btbd\b|allowance|optional|alternate|or\s+equal|nic\b", text):
        anchor = _clip_anchor(text, 64)
        return f"Lock BOM choice for \"{anchor}\" — include as written, allowance, or remove?"
    if re.search(r"(?i)\b(?:qty|quantity|each|lot)\b|\d+\s*x\b", text):
        anchor = _clip_anchor(text, 64)
        return f"Confirm qty/model for \"{anchor}\" is authoritative for this quote."
    return None


# ── PM-brain coverage: questions a sharp PM always pressures ──────────

# (rule_suffix, domain, label, question, trigger_re, severity, score)
_PM_COVERAGE: tuple[tuple[str, str, str, str, str, str, float], ...] = (
    (
        "site_list_lock",
        "site",
        "Authoritative site list",
        "Which sites are in this quote wave — confirm the authoritative address list and any deferrals.",
        r"(?i)\b(?:site|location|address|facility|branch|store)\b",
        "blocker",
        0.92,
    ),
    (
        "onsite_contact",
        "site",
        "Day-of onsite contact",
        "Who is the day-of onsite contact per site, and how do we reach them?",
        r"(?i)\b(?:contact|site\s+lead|facilities|on[\-\s]?site|poc)\b",
        "blocker",
        0.9,
    ),
    (
        "access_badging",
        "site",
        "Access / escort / badging",
        "Confirm site access, escort, badging, and after-hours requirements for every in-scope site.",
        r"(?i)\b(?:access|escort|badg(?:e|ing)|after[\-\s]?hours|loading\s+dock|security)\b",
        "blocker",
        0.91,
    ),
    (
        "work_hours",
        "site",
        "Approved work window",
        "What are the approved work hours / blackout windows for install and cutover?",
        r"(?i)\b(?:after[\-\s]?hours|maintenance\s+window|cutover|change\s+window|business\s+hours|outage)\b",
        "warning",
        0.88,
    ),
    (
        "hardware_furnish",
        "hardware",
        "CF vs OFE hardware",
        "What hardware is customer-furnished vs PurTera-furnished — and who stages it to site?",
        r"(?i)\b(?:ofe|owner[\-\s]?furnish|customer[\-\s]?furnish|bom|hardware|equipment|by\s+others)\b",
        "blocker",
        0.93,
    ),
    (
        "pathway_ownership",
        "field_evidence",
        "Pathway / conduit ownership",
        "Who owns pathway (conduit, sleeves, fish, raceway, drywall patch) — PurTera, GC, or customer?",
        r"(?i)\b(?:conduit|pathway|raceway|in[\-\s]?wall|sleeve|drywall|fish|cable\s+pull)\b",
        "blocker",
        0.92,
    ),
    (
        "acceptance",
        "project",
        "Acceptance sign-off",
        "Who signs acceptance, and what is the pass/fail checklist before we invoice?",
        r"(?i)\b(?:acceptance|sign[\-\s]?off|poc|sop|commission|uat)\b",
        "blocker",
        0.9,
    ),
    (
        "payment_gate",
        "commercial",
        "Payment / deposit gate",
        "Confirm payment terms that gate scheduling (deposit %, milestones, Net-X).",
        r"(?i)\b(?:deposit|50%|invoice|net\s*\d+|payment|purchase\s+order|\bpo\b)\b",
        "warning",
        0.86,
    ),
    (
        "change_order",
        "commercial",
        "Change-order path",
        "What change-order path applies when field conditions differ from the quote assumptions?",
        r"(?i)\b(?:change\s+order|t\s*&\s*m|time\s+and\s+materials|allowance|assume)\b",
        "warning",
        0.85,
    ),
    (
        "qty_lock",
        "hardware",
        "Quantity lock",
        "Confirm authoritative quantities for every billable device/drop — which source wins if docs disagree?",
        r"(?i)\b(?:qty|quantity|\d+\s*(?:x|×)\s*|\baps?\b|cameras?|drops?|ports?)\b",
        "blocker",
        0.89,
    ),
    (
        "first_site",
        "site",
        "First site / sequence",
        "Which site is first, what is the sequence, and what readiness gate starts mobilization?",
        r"(?i)\b(?:first\s+site|pilot|phase|rollout|sequence|schedule|mobiliz)\b",
        "warning",
        0.87,
    ),
    (
        "exclusions",
        "commercial",
        "Exclusions acknowledged",
        "Confirm customer acknowledges key exclusions (power, conduit, patch/paint, OFE, permits) as written.",
        r"(?i)\b(?:exclusion|not\s+included|by\s+others|out\s+of\s+scope|customer\s+responsib)\b",
        "warning",
        0.84,
    ),
    (
        "wireless_design",
        "wireless",
        "Wireless design inputs",
        "Confirm AP count/model, SSID/VLAN assumptions, and whether a predictive/RF survey is in-scope.",
        r"(?i)\b(?:access\s+point|\baps?\b|ssid|wlan|wireless|heatmap|rf\s+survey)\b",
        "blocker",
        0.9,
    ),
    (
        "av_keep_remove",
        "audio_visual",
        "AV keep vs remove",
        "Which existing displays/codecs stay, which are removed, and what is reused vs new BOM?",
        r"(?i)\b(?:display|tv\b|codec|teams\s+room|zoom\s+room|hdmi|av\s+install)\b",
        "blocker",
        0.9,
    ),
    (
        "security_roe",
        "project",
        "Security test rules of engagement",
        "Confirm rules of engagement: environments, time windows, allow-lists, and emergency stop contacts.",
        r"(?i)\b(?:penetrat|pentest|vulnerab|assessment|red\s+team|allow[\-\s]?list)\b",
        "blocker",
        0.91,
    ),
)


def pm_coverage_specs() -> tuple[tuple[str, str, str, str, str, str, float], ...]:
    return _PM_COVERAGE


def evidence_blob_from_atoms(atoms: list[Any]) -> str:
    parts: list[str] = []
    for a in atoms:
        if not isinstance(a, dict):
            continue
        t = str(a.get("text") or "").strip()
        if t:
            parts.append(t)
        if len(parts) > 400:
            break
    return "\n".join(parts)
