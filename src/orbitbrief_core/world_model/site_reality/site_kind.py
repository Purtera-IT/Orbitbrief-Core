"""Typed site-candidate classifier (PR 11 — Site Reality v2).

The original site_reality filter only blocked obvious banned product
terms (Belden, Cat6, ServiceNow). Real corpus runs still produced
clusters like ``role:customer network engineer``, ``priority:p2 high``,
``equipment:poweredge r760xd vms``, ``generic:some mdf``,
``service:ms its vpn service desk``. None of those are physical sites.

This module classifies a ``site:*`` candidate into one of:

    physical_site         (campus / school / hospital / library)
    building              (district core, main campus, annex, tower)
    address               (street + number + suffix)
    room_or_closet        (MDF, IDF, room, closet) — must be anchored
                          to a parent physical_site to be published
    organization          (district, agency, department, customer)
    role_or_person        (engineer, architect, director, owner)
    equipment_or_product  (PowerEdge, Cat6, BMS VM, switch)
    service_or_software   (ServiceNow, VPN service desk, vendor SaaS)
    risk_or_priority      (P2 High, critical, blocker)
    generic_phrase        ("each MDF", "some IDF", "one closet")
    unknown               (couldn't decide)

The orchestrator then publishes only ``physical_site``, ``building``,
``address``, and ``room_or_closet`` (the last only when
``parent_cluster_id`` is non-empty).
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Any


class SiteCandidateKind(str, Enum):
    physical_site = "physical_site"
    building = "building"
    room_or_closet = "room_or_closet"
    address = "address"
    organization = "organization"
    role_or_person = "role_or_person"
    equipment_or_product = "equipment_or_product"
    service_or_software = "service_or_software"
    risk_or_priority = "risk_or_priority"
    generic_phrase = "generic_phrase"
    unknown = "unknown"


# What kinds are publishable as their own physical-site cluster?
PUBLISHABLE_KINDS: frozenset[SiteCandidateKind] = frozenset(
    {
        SiteCandidateKind.physical_site,
        SiteCandidateKind.building,
        SiteCandidateKind.address,
    }
)
# What kinds may be published only when anchored to a parent
# physical-site cluster (e.g. "MDF Room 102" anchored to "Banks HS").
PUBLISHABLE_IF_ANCHORED: frozenset[SiteCandidateKind] = frozenset(
    {SiteCandidateKind.room_or_closet}
)


# ─────────────────────────── pattern packs ──────────────────────────


_PHYSICAL_SITE_RE = re.compile(
    r"\b("
    r"school|elementary|middle\s+school|high\s+school|"
    r"campus|college|university|hospital|clinic|library|"
    r"auditorium|courthouse|courtroom|warehouse|plant|"
    r"facility|office|venue|stadium|arena|airport|terminal|"
    # PR21 — broaden physical-site vocabulary so real sites like
    # "Chicago Housing Authority Operations Center", "Piedmont
    # Police Station", "Perry Street Parking Structure", "Santa
    # Monica Analytics Lab" classify correctly. The vendor-product
    # name "Security Center" is still blocked at the cluster.py
    # negative-regex layer.
    r"operations\s+center|command\s+center|distribution\s+center|"
    r"data\s+center|datacenter|training\s+center|research\s+center|"
    r"fulfillment\s+center|service\s+center|community\s+center|"
    r"convention\s+center|"
    r"police\s+station|fire\s+station|"
    r"parking\s+structure|parking\s+deck|parking\s+garage|"
    r"housing\s+authority|housing\s+development|"
    r"analytics\s+lab|research\s+lab|innovation\s+lab|test\s+lab|"
    r"city\s+hall|town\s+hall|town\s+center|"
    r"campus\s+center|operations\s+building|"
    # PR6 (post-v3) — yard / event staging / pole camera yard.
    # Real physical sites that the previous regex missed
    # ("Milwaukee Event Operations Pole Camera Yard").
    r"yard|staging\s+area|staging\s+yard|event\s+yard|"
    r"camera\s+yard|pole\s+camera\s+yard|"
    r"event\s+operations|event\s+command\s+staging|"
    # University name suffixes — "Virginia Tech", "Texas A&M",
    # "Georgia Tech", "Cal Poly", "Penn State", "MIT", "Caltech",
    # "VCU". These are place names with no other classification
    # signal in the bare canonical name. Anchored with a leading
    # capital so we don't match "tech" inside "technician".
    r"(?:^|\s)(?:tech|polytechnic|institute|state|a&m|poly)$"
    r")",
    re.I,
)
_BUILDING_RE = re.compile(
    r"\b("
    r"building|bldg|tower|annex|wing|hall|"
    r"district\s+core|main\s+campus|main\s+building|"
    r"east\s+wing|west\s+wing|north\s+wing|south\s+wing"
    r")\b",
    re.I,
)
_ADDRESS_RE = re.compile(
    r"\b\d{2,6}\s+[a-z0-9 .'-]+\s+("
    r"st|street|rd|road|ave|avenue|dr|drive|"
    r"blvd|boulevard|way|lane|ln|pkwy|parkway|hwy|highway|"
    # PR6 (post-v3) — common street-name suffixes that aren't
    # "Avenue/Street/Drive" (Broadway, Plaza, Place, Court,
    # Trail, Square, Loop, Crescent, Terrace, Row).
    r"broadway|plaza|place|pl|court|ct|trail|square|sq|loop|"
    r"crescent|cres|terrace|ter|row"
    r")\b",
    re.I,
)
_ROOM_CLOSET_RE = re.compile(
    r"\b("
    r"mdf(?:\s*\d+)?|idf(?:\s*\d+)?|"
    r"telecom\s+(?:room|closet)|server\s+room|equipment\s+room|"
    r"comm(?:s|unications)?\s+(?:room|closet)|wiring\s+closet|"
    r"data\s+closet|patch\s+room|"
    r"room\s*\d+|suite\s*\d+|closet\s*\d+"
    r")\b",
    re.I,
)
_ORGANIZATION_RE = re.compile(
    r"\b("
    r"district|agency|department|customer|client|"
    r"public\s+schools|county|city|state|federal|"
    r"corporation|llc|inc|company"
    r")\b",
    re.I,
)
_ROLE_PERSON_RE = re.compile(
    r"\b("
    r"engineer|architect|director|manager|owner|admin(?:istrator)?|"
    # Drop bare "tech" — it's a common place-name suffix
    # ("Virginia Tech", "Georgia Tech"). Keep "technician".
    r"technician|operator|analyst|specialist|consultant|"
    r"president|vp|cio|cto|cso|ciso|"
    r"contact|sponsor|stakeholder|approver"
    r")\b",
    re.I,
)
_EQUIPMENT_PRODUCT_RE = re.compile(
    r"\b("
    r"poweredge|optiplex|nimble|isilon|"
    r"cat\s?6|cat\s?6a|cat\s?5e|"
    r"belden|panduit|commscope|leviton|"
    r"cisco|meraki|juniper|aruba|fortinet|fortigate|palo\s+alto|"
    r"genetec|axis|hanwha|milestone|lenel|hid|mercury|"
    r"apc|generac|liebert|"
    # PR6 (post-v3) — dropped bare ``camera`` and ``reader`` because
    # they appear inside legitimate site names ("Pole Camera Yard",
    # "Card Reader Lab"). Vendor names (Genetec, Axis, Hanwha,
    # Milestone, Avigilon, HID, Mercury) still cover real product
    # detection. Server/switch/router/firewall stay because they
    # describe equipment rather than place names.
    r"ups|server|switch|router|firewall|controller|appliance|"
    r"sensor|breaker|outlet|jack|patch|cable|"
    r"r\d{3}xd|r\d{3}|wsc?\d+"
    r")\b",
    re.I,
)
_SERVICE_SOFTWARE_RE = re.compile(
    r"\b("
    r"servicenow|pagerduty|logicmonitor|sentinel|onguard|synergis|"
    r"streamvault|omnicast|xprotect|"
    r"vpn|service\s+desk|help\s*desk|noc|soc|saas|paas|iaas|"
    r"vlan|management\s+vlan|mgmt\s+vlan|"
    r"microsoft\s+\w+|office\s+365|azure|aws|google\s+workspace"
    r")\b",
    re.I,
)
_RISK_PRIORITY_RE = re.compile(
    r"\b("
    r"p[0-9]\s*(?:critical|high|medium|low)|"
    r"critical|blocker|urgent|severity|priority|"
    r"high\s+risk|low\s+risk|medium\s+risk"
    r")\b",
    re.I,
)
_GENERIC_PHRASE_RE = re.compile(
    r"\b("
    r"each|some|every|any|all|the|a|an|several|various|"
    r"site|location|place|area"
    r")\s+(mdf|idf|room|closet|building|site|location)\b",
    re.I,
)
# PR (post-2-case review F1) — known noise patterns that came from
# project_metadata, source-reference rows, table-header fragments,
# survey-item header rows, or generic acceptance/checklist nouns
# that the entity_resolution stage incorrectly produced as site
# candidates. Reject hard.
_NOISE_SITE_RE = re.compile(
    r"\b("
    r"safetyculture|tts\s+cabling\s+survey|"
    r"survey\s+item\s+status|acceptance\s+item|nonconforming\s+items?|"
    r"po\s+required|change\s+advisory\s+board|cab\s+meeting|"
    r"cmdb|target\s+go[-\s]?live|managed\s+services\s+acceptance|"
    r"av\s+low\s+voltage\s+readiness|generated\s+artifact|"
    r"customer\s+restrictions|pm\s+connection|"
    r"open\s+customer|cori|gsa\s+it\s+services|"
    # Table-header fragment patterns: ``<noun> <noun>`` of generic
    # words that no real site would be named.
    r"^\s*site\s*$|^\s*field\s+note\s*$"
    r")\b",
    re.I,
)


def classify_site_candidate(
    site_key: str,
    ent: dict[str, Any] | None = None,
    *,
    evidence_blob: str = "",
) -> SiteCandidateKind:
    """Classify a ``site:*`` candidate based on its canonical name + key.

    Order of operations matters — we test the most specific /
    discriminative patterns first.

    PR6 (post-v3 review) adds an optional ``evidence_blob`` arg.
    Cluster.py passes the entity's atom-evidence text so a site like
    "Milwaukee Event Operations Pole Camera Yard" with strong
    address + MDF + provider evidence promotes to physical_site even
    when the bare name doesn't match the positive regex.
    """
    # Classify on the canonical_name when available; only fall back to
    # the site_key surface form when no canonical_name exists. Joining
    # the two created spurious matches like "Building A" + "building a"
    # → "a building" → generic_phrase, dropping legitimate sites.
    cn = ""
    if ent:
        cn = (ent.get("canonical_name") or "").strip()
    name = cn if cn else site_key.replace("site:", "").replace("_", " ")
    name = name.strip()
    if not name:
        return SiteCandidateKind.unknown
    # Combined view for evidence-aware promotion. Negative checks
    # below still run on the bare name only so vendor product names
    # don't get rescued by adjacent address strings.
    combined = f"{name} {evidence_blob}".strip()

    # Hard rejects first so they can't be rescued by an accidental
    # "campus" or "center" mention later in the candidate text.
    if _NOISE_SITE_RE.search(name):
        return SiteCandidateKind.generic_phrase
    if _RISK_PRIORITY_RE.search(name):
        return SiteCandidateKind.risk_or_priority
    if _ROLE_PERSON_RE.search(name):
        return SiteCandidateKind.role_or_person
    if _EQUIPMENT_PRODUCT_RE.search(name):
        return SiteCandidateKind.equipment_or_product
    if _SERVICE_SOFTWARE_RE.search(name):
        return SiteCandidateKind.service_or_software
    if _GENERIC_PHRASE_RE.search(name):
        return SiteCandidateKind.generic_phrase

    # Then accepts.
    if _ADDRESS_RE.search(name):
        return SiteCandidateKind.address
    if _PHYSICAL_SITE_RE.search(name):
        return SiteCandidateKind.physical_site
    if _PHYSICAL_SITE_RE.search(combined):
        return SiteCandidateKind.physical_site
    if _BUILDING_RE.search(name):
        return SiteCandidateKind.building
    if _ROOM_CLOSET_RE.search(name):
        return SiteCandidateKind.room_or_closet
    if _ORGANIZATION_RE.search(name):
        return SiteCandidateKind.organization

    # PR6 (post-v3) — evidence-aware promotion. When the bare name
    # is unknown but the entity has STRONG site evidence (address +
    # site-id, address + MDF/IDF, address + provider, address +
    # access language), promote to physical_site. Used to rescue
    # event-yard / pole-camera-yard / portable-LTE sites whose
    # canonical_name doesn't include any positive vocabulary.
    if evidence_blob:
        has_address = bool(_ADDRESS_RE.search(combined))
        has_site_id = bool(re.search(r"\bS\d{2,4}\b", combined))
        has_mdf_idf = bool(re.search(r"\b(MDF|IDF)[-_A-Z0-9]*\b", combined, re.I))
        has_provider = bool(
            re.search(
                r"\b(city\s+fiber|firstnet|lte|comcast|at&t|verizon|cogent|"
                r"metro[-\s]?e|dia\s+fiber)\b",
                combined,
                re.I,
            )
        )
        has_access = bool(
            re.search(
                r"\b(access|credentialed|escort|badge|24x7|after[-\s]?hours|"
                r"event[-\s]?driven)\b",
                combined,
                re.I,
            )
        )
        if has_address and (
            has_site_id or has_mdf_idf or has_provider or has_access
        ):
            return SiteCandidateKind.physical_site

    return SiteCandidateKind.unknown


def is_publishable(
    kind: SiteCandidateKind, *, parent_cluster_id: str | None = None
) -> bool:
    """Publishability gate. Room/closet kinds must have a parent
    physical-site cluster — a stand-alone "MDF" cluster is meaningless."""
    if kind in PUBLISHABLE_KINDS:
        return True
    if kind in PUBLISHABLE_IF_ANCHORED:
        return bool(parent_cluster_id)
    return False


__all__ = [
    "SiteCandidateKind",
    "PUBLISHABLE_KINDS",
    "PUBLISHABLE_IF_ANCHORED",
    "classify_site_candidate",
    "is_publishable",
]
