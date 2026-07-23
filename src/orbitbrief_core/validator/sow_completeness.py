"""SOW completeness validator for OrbitBrief substrate outputs.

This module is intentionally substrate-only. It does not judge LLM brain text.
It asks a simpler PM-audit question:

    Given the selected domain packs and the evidence substrate, which SOW-critical
    facts are missing, weakly represented, or only implied?

Inputs are the same objects the rest of OrbitBrief already has:

* selected_pack_ids from pack_prior
* atoms from the parser-os envelope
* packets from packetizer/certifier output
* site clusters from site_reality

The rules live in ``validator/data/sow_completeness_rules.yaml`` so PMs and
lead engineers can expand the coverage without touching Python.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from importlib import resources
import re
from typing import Any, Iterable, Mapping

import yaml


_STATUS_ORDER = {"green": 0, "yellow": 1, "red": 2}
_SEVERITY_TO_STATUS = {"info": "green", "warning": "yellow", "blocker": "red"}
_PUBLISHABLE_SITE_KINDS = {"physical_site", "building", "address", "room_or_closet"}

# v9: TRUST the trained service-router head. When it confidently routes a deal to a
# primary service, restrict the active SOW domains to that primary (+ any secondary
# it returns + always-on infra) instead of the over-broad pack-prior selection +
# evidence inference. Without this, a confident `audio_visual` deal still runs the
# msp / datacenter / low_voltage_cabling checklists — producing phantom blockers
# from the "Data Center Warehouse" *name* and incidental, explicitly out-of-scope
# cable mentions. Falls back to the union when the head abstains or scores < TAU.
_ALWAYS_ON_DOMAINS = frozenset({"commercial", "global"})
_ROUTER_TRUST_TAU = 0.6


def _router_primary(
    service_routing: Mapping[str, Any] | None,
) -> tuple[str | None, float]:
    """(primary_domain, confidence) from a confident, non-abstained service-router
    head result; (None, 0.0) when missing / disabled / abstained / unparseable."""
    if not isinstance(service_routing, Mapping):
        return None, 0.0
    if not service_routing.get("enabled") or service_routing.get("abstained"):
        return None, 0.0
    primary = str(service_routing.get("primary") or "").strip()
    if not primary:
        return None, 0.0
    try:
        conf = float(service_routing.get("confidence") or 0.0)
    except (TypeError, ValueError):
        conf = 0.0
    return primary, conf


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _flatten_value(value: Any) -> str:
    """Flatten nested atom.value dictionaries without losing field names."""
    parts: list[str] = []
    if isinstance(value, Mapping):
        for k, v in value.items():
            parts.append(str(k))
            parts.append(_flatten_value(v))
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            parts.append(_flatten_value(item))
    elif value is not None:
        parts.append(str(value))
    return " ".join(p for p in parts if p)


def _physical_atom_has_location(atom: Mapping[str, Any]) -> bool:
    value = atom.get("value") or atom.get("structured") or {}
    if not isinstance(value, Mapping):
        return False
    street = str(value.get("street_address") or value.get("address") or "").strip()
    city = str(value.get("city") or "").strip()
    state = str(value.get("state") or "").strip()
    zipc = str(value.get("zip") or value.get("postal_code") or "").strip()
    if street and (city or state or zipc):
        return True
    return bool(street and re.search(r"\b\d{1,6}\b", street))


def _atom_text(atom: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for key in ("raw_text", "text", "normalized_text", "claim", "normalized_claim"):
        val = atom.get(key)
        if isinstance(val, str) and val.strip():
            parts.append(val)
    parts.append(_flatten_value(atom.get("value")))
    for key in _as_list(atom.get("entity_keys")):
        parts.append(str(key).replace(":", " ").replace("_", " "))
    for ref in _as_list(atom.get("source_refs")):
        if not isinstance(ref, Mapping):
            continue
        parts.append(str(ref.get("filename") or ""))
        locator = ref.get("locator") or {}
        if isinstance(locator, Mapping):
            parts.append(_flatten_value(locator))
    return "\n".join(p for p in parts if p)


def _packet_text(packet: Mapping[str, Any]) -> str:
    parts = [
        _text(packet.get("family")),
        _text(packet.get("packet_family")),
        _text(packet.get("anchor_key")),
        _text(packet.get("anchor_type")),
        _flatten_value(packet),
    ]
    return "\n".join(p for p in parts if p)


def _site_text(cluster: Mapping[str, Any]) -> str:
    return "\n".join(
        p
        for p in (
            _text(cluster.get("canonical_name")),
            _text(cluster.get("canonical_key")),
            _text(cluster.get("kind")),
            _flatten_value(cluster),
        )
        if p
    )


def _compile(patterns: Iterable[str]) -> list[re.Pattern[str]]:
    return [re.compile(p, re.I | re.M | re.S) for p in patterns if str(p).strip()]


@dataclass(frozen=True)
class CorpusView:
    """Searchable view over atoms, packets, and site clusters."""

    atoms: tuple[Mapping[str, Any], ...] = ()
    packets: tuple[Mapping[str, Any], ...] = ()
    site_clusters: tuple[Mapping[str, Any], ...] = ()
    atom_text: str = ""
    packet_text: str = ""
    site_text: str = ""
    all_text: str = ""
    atom_types: frozenset[str] = frozenset()
    packet_families: frozenset[str] = frozenset()
    publishable_site_count: int = 0

    @classmethod
    def build(
        cls,
        *,
        atoms: Iterable[Mapping[str, Any]] = (),
        packets: Iterable[Mapping[str, Any]] = (),
        site_clusters: Iterable[Mapping[str, Any]] = (),
    ) -> "CorpusView":
        atom_tuple = tuple(atoms or ())
        packet_tuple = tuple(packets or ())
        site_tuple = tuple(site_clusters or ())
        atom_blob = "\n".join(_atom_text(a) for a in atom_tuple)
        packet_blob = "\n".join(_packet_text(p) for p in packet_tuple)
        site_blob = "\n".join(_site_text(s) for s in site_tuple)
        atom_types = frozenset(str(a.get("atom_type") or "") for a in atom_tuple)
        packet_families = frozenset(
            str(p.get("family") or p.get("packet_family") or "") for p in packet_tuple
        )
        pub_sites = sum(
            1
            for s in site_tuple
            if str(s.get("kind") or "") in _PUBLISHABLE_SITE_KINDS
        )
        if pub_sites == 0:
            pub_sites = sum(
                1
                for atom in atom_tuple
                if str(atom.get("atom_type") or "") == "physical_site"
                and _physical_atom_has_location(atom)
            )
        return cls(
            atoms=atom_tuple,
            packets=packet_tuple,
            site_clusters=site_tuple,
            atom_text=atom_blob,
            packet_text=packet_blob,
            site_text=site_blob,
            all_text="\n".join([atom_blob, packet_blob, site_blob]),
            atom_types=atom_types,
            packet_families=packet_families,
            publishable_site_count=pub_sites,
        )

    def has_any_regex(self, patterns: Iterable[str], *, field: str = "all") -> bool:
        blob = getattr(self, f"{field}_text", self.all_text) if field != "all" else self.all_text
        return any(rx.search(blob) for rx in _compile(patterns))

    def has_all_regex(self, patterns: Iterable[str], *, field: str = "all") -> bool:
        compiled = _compile(patterns)
        if not compiled:
            return True
        blob = getattr(self, f"{field}_text", self.all_text) if field != "all" else self.all_text
        return all(rx.search(blob) for rx in compiled)

    def count_regex(self, patterns: Iterable[str], *, field: str = "all") -> int:
        blob = getattr(self, f"{field}_text", self.all_text) if field != "all" else self.all_text
        count = 0
        for rx in _compile(patterns):
            count += len(rx.findall(blob))
        return count


@dataclass(frozen=True)
class SowCompletenessFinding:
    rule_id: str
    domain_id: str
    label: str
    severity: str
    message: str
    suggested_open_question: str
    evidence_searched: dict[str, Any] = field(default_factory=dict)
    observed_support: dict[str, Any] = field(default_factory=dict)

    @property
    def status_impact(self) -> str:
        return _SEVERITY_TO_STATUS.get(self.severity, "yellow")

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "domain_id": self.domain_id,
            "label": self.label,
            "severity": self.severity,
            "message": self.message,
            "suggested_open_question": self.suggested_open_question,
            "evidence_searched": self.evidence_searched,
            "observed_support": self.observed_support,
        }


@dataclass(frozen=True)
class SowCompletenessResult:
    status: str
    active_domain_ids: tuple[str, ...]
    findings: tuple[SowCompletenessFinding, ...]
    coverage: dict[str, Any] = field(default_factory=dict)

    @property
    def blocker_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "blocker")

    @property
    def warning_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "warning")

    @property
    def info_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "info")

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "active_domain_ids": list(self.active_domain_ids),
            "summary": {
                "total_findings": len(self.findings),
                "blocker": self.blocker_count,
                "warning": self.warning_count,
                "info": self.info_count,
            },
            "coverage": self.coverage,
            "findings": [f.to_dict() for f in self.findings],
        }


def load_sow_rules() -> dict[str, Any]:
    """Load the YAML rulebook bundled with Orbitbrief-Core."""
    package = "orbitbrief_core.validator.data"
    with resources.files(package).joinpath("sow_completeness_rules.yaml").open(
        "r", encoding="utf-8"
    ) as f:
        return yaml.safe_load(f) or {}


def _canonical_pack_ids(selected_pack_ids: Iterable[str], rules: Mapping[str, Any]) -> set[str]:
    aliases = rules.get("pack_aliases") or {}
    out: set[str] = set()
    for raw in selected_pack_ids or ():
        pack = str(raw)
        out.add(pack)
        for canonical in _as_list(aliases.get(pack)):
            out.add(str(canonical))
    return out


_DEFAULT_INFERENCE_THRESHOLD = 8
_DEFAULT_INFERENCE_MIN_HITS = 12


def _domain_required_anchor_satisfied(
    domain_id: str, domain: Mapping[str, Any], corpus: "CorpusView"
) -> bool:
    """Boss-review v8 F6/F8 — some domains require an additional
    "real scope" anchor before activating, so generic-vocabulary
    matches can't pull them in.

    Driven by ``domain.required_anchor_regex_any`` (default
    threshold = 2 distinct matches) and
    ``domain.required_anchor_min_distinct_hits`` (override).
    """
    anchors = domain.get("required_anchor_regex_any") or []
    if not anchors:
        return True
    min_hits = int(domain.get("required_anchor_min_distinct_hits") or 2)
    text = corpus.all_text
    distinct: set[str] = set()
    for pattern in anchors:
        try:
            compiled = re.compile(pattern, re.I)
        except re.error:
            continue
        for m in compiled.finditer(text):
            distinct.add(m.group(0).lower())
            if len(distinct) >= min_hits:
                return True
    return False


def _infer_domains_from_evidence(corpus: CorpusView, rules: Mapping[str, Any]) -> set[str]:
    """Activate a domain by evidence only when signal is OVERWHELMING.

    Boss-review F9 (post-2-case review) found that the
    ``>=4 distinct alternatives`` threshold was still too loose:
    cabling-only intakes activated security_camera and
    camera_vms_operations because BOM rows happened to mention
    "AXIS camera adapter" or "video patch panel" enough times.

    New rule:
    * inference is a SAFETY NET, not the primary activation
      mechanism. The router's ``selected_pack_ids`` is the
      primary activation signal (passed in by the caller).
    * to auto-activate via evidence, a domain must clear BOTH:
        - at least ``inference_threshold`` distinct trigger
          alternatives appear in the corpus, AND
        - at least ``inference_min_hits`` total trigger matches.
    * default thresholds are intentionally high (8 distinct, 12
      total). Per-domain overrides live in the YAML rulebook
      under ``domains.<id>.inference_threshold`` /
      ``inference_min_hits`` for cases where a smaller cluster
      should still fire (e.g., low_voltage_cabling = 4 distinct
      because cabling vocabulary is narrower).
    """
    inferred: set[str] = set()
    for domain_id, domain in (rules.get("domains") or {}).items():
        triggers = domain.get("scope_triggers") or []
        if not triggers:
            continue
        compiled = _compile(triggers)
        text = corpus.all_text
        distinct_alternatives: set[str] = set()
        total_hits = 0
        for pattern in compiled:
            for m in pattern.finditer(text):
                distinct_alternatives.add(m.group(0).lower())
                total_hits += 1
        threshold = int(domain.get("inference_threshold") or _DEFAULT_INFERENCE_THRESHOLD)
        min_hits = int(domain.get("inference_min_hits") or _DEFAULT_INFERENCE_MIN_HITS)
        if len(distinct_alternatives) >= threshold and total_hits >= min_hits:
            if _domain_required_anchor_satisfied(str(domain_id), domain, corpus):
                inferred.add(str(domain_id))
    return inferred


def _check_satisfied(check: Mapping[str, Any], corpus: CorpusView) -> tuple[bool, dict[str, Any]]:
    evidence = check.get("evidence") or {}

    observed: dict[str, Any] = {
        "matched_regex": False,
        "matched_atom_type": False,
        "matched_packet_family": False,
        "publishable_site_count": corpus.publishable_site_count,
    }

    if evidence.get("requires_site_cluster") and corpus.publishable_site_count <= 0:
        return False, observed

    # ``match_mode: any`` — satisfy if ANY positive matcher hits (atom type
    # OR regex OR packet family). Default remains AND across present selectors.
    match_any = str(evidence.get("match_mode") or "").strip().lower() == "any"

    packet_required = bool(evidence.get("requires_packet_family"))
    atom_required = bool(evidence.get("requires_atom_type"))
    any_regex = evidence.get("any_regex") or []
    all_regex = evidence.get("all_regex") or []
    min_regex_count = evidence.get("min_regex_count")
    search_field = str(evidence.get("search_field") or "all")

    if packet_required:
        required = {str(x) for x in _as_list(evidence.get("requires_packet_family"))}
        observed["matched_packet_family"] = bool(required & corpus.packet_families)

    if atom_required:
        required = {str(x) for x in _as_list(evidence.get("requires_atom_type"))}
        observed["matched_atom_type"] = bool(required & corpus.atom_types)

    if any_regex:
        observed["matched_regex"] = corpus.has_any_regex(any_regex, field=search_field)

    if all_regex:
        observed["matched_all_regex"] = corpus.has_all_regex(all_regex, field=search_field)

    if min_regex_count is not None:
        patterns = evidence.get("count_regex") or any_regex or all_regex
        observed["regex_count"] = corpus.count_regex(patterns, field=search_field)

    positive_selectors = [
        k
        for k in (
            "requires_packet_family",
            "requires_atom_type",
            "any_regex",
            "all_regex",
            "min_regex_count",
        )
        if evidence.get(k)
    ]
    # If a check supplied no explicit evidence selectors, treat it as not satisfied.
    if not positive_selectors and not evidence.get("requires_site_cluster"):
        return False, observed

    if match_any:
        any_hit = False
        if packet_required and observed["matched_packet_family"]:
            any_hit = True
        if atom_required and observed["matched_atom_type"]:
            any_hit = True
        if any_regex and observed["matched_regex"]:
            any_hit = True
        if all_regex and observed.get("matched_all_regex"):
            any_hit = True
        if min_regex_count is not None and observed.get("regex_count", 0) >= int(
            min_regex_count
        ):
            any_hit = True
        return any_hit, observed

    if packet_required and not observed["matched_packet_family"]:
        return False, observed
    if atom_required and not observed["matched_atom_type"]:
        return False, observed
    if any_regex and not observed["matched_regex"]:
        return False, observed
    if all_regex and not observed.get("matched_all_regex"):
        return False, observed
    if min_regex_count is not None and observed.get("regex_count", 0) < int(
        min_regex_count
    ):
        return False, observed

    return True, observed


def _severity_status(findings: Iterable[SowCompletenessFinding]) -> str:
    status = "green"
    for finding in findings:
        impact = finding.status_impact
        if _STATUS_ORDER[impact] > _STATUS_ORDER[status]:
            status = impact
    return status


_CONFIG_ONLY_WIRELESS_GAP_IDS = frozenset({
    "wireless.ap_count_model",
    "wireless.ap_cabling_spec",
    "wireless.poe_class_budget",
    "wireless.dfs_channel_policy_missing",
    "wireless.heatmap_deliverables",
    "wireless.mounting_access",
    "wireless.poe_switch_dependency",
    "wireless.poe_class_per_ap_missing",
    "wireless.mounting_locations_missing",
    "wireless.post_validation_walkthrough_missing",
    "wireless.owner_furnished_boundary_missing",
    "wireless.per_ap_cable_certification_level_missing",
    "wireless.survey_type",
    "wireless.wips_rogue_ap_policy_missing",
})

# SD-WAN / Meraki / remote-hands multi-site *install* engagements reuse the
# network_maintenance pack for routing, but ongoing-ops SOW checks (firmware
# gold image, OEM TAC, VLAN audit cadence, SmartNet tier) are not applicable
# until the estate is in maintenance. Suppress those when install evidence is
# present — same spirit as config_only wireless suppression.
_NETWORK_INSTALL_EVIDENCE_RE = re.compile(
    r"(?:"
    r"\b(?:sd[\s\-]?wan|sdwan)\b|"
    r"\bmeraki\s+mx\b|"
    r"\b(?:mpls\s+to\s+sd|transition(?:ing)?\s+from\s+mpls)\b|"
    r"\b(?:remote\s+hands|smart\s+hands)\b.{0,40}\b(?:site|office|location|install)|"
    r"\b(?:circuit(?:s)?\s+(?:turn[\s\-]?up|at\s+each)|turn(?:ing)?\s+on\s+circuits?)\b"
    r")",
    re.I,
)
_NETWORK_INSTALL_OPS_GAP_IDS = frozenset({
    "network_maintenance.coverage_tier",
    "network_maintenance.firmware_change",
    "network_maintenance.firmware_baseline_missing",
    "network_maintenance.patch_window_change_calendar_missing",
    "network_maintenance.oem_tac_escalation_missing",
    "network_maintenance.vlan_port_audit_cadence_missing",
    "network_maintenance.circuit_demarc_responsibility_missing",
    # Install / turn-up jobs are not ongoing-ops engagements — these checks
    # only yellow or clutter the handoff with irrelevant "info" leftovers.
    "network_maintenance.routing_failover",
    "network_maintenance.port_vlan_wan",
    "network_maintenance.device_inventory",
})


def _corpus_has_network_install(corpus: CorpusView) -> bool:
    blob = " ".join(_atom_text(a) for a in corpus.atoms)
    return bool(blob and _NETWORK_INSTALL_EVIDENCE_RE.search(blob))


def _parser_quote_delivery_model(atoms: Iterable[Mapping[str, Any]]) -> str:
    for atom in atoms:
        value = atom.get("value") or atom.get("structured") or {}
        if not isinstance(value, Mapping):
            continue
        context = value.get("quote_context") or {}
        if not isinstance(context, Mapping):
            continue
        delivery_model = str(context.get("delivery_model") or "").strip().lower()
        if delivery_model:
            return delivery_model
    return ""


def evaluate_sow_completeness(
    *,
    selected_pack_ids: Iterable[str],
    atoms: Iterable[Mapping[str, Any]],
    packets: Iterable[Mapping[str, Any]] = (),
    site_clusters: Iterable[Mapping[str, Any]] = (),
    rules: Mapping[str, Any] | None = None,
    infer_domains: bool = True,
    include_global: bool = True,
    service_routing: Mapping[str, Any] | None = None,
) -> SowCompletenessResult:
    """Evaluate SOW completeness across all selected/inferred domains.

    Parameters
    ----------
    selected_pack_ids:
        Pack ids from pack_prior selected_pack_ids plus top_pack_id if needed.
    atoms:
        parser-os evidence atoms. The evaluator searches raw_text, text,
        normalized_text, value, entity_keys, source_refs and locators.
    packets:
        Certified packets. Rule evidence can require packet families.
    site_clusters:
        SiteReality clusters. Rule evidence can require publishable site clusters.
    infer_domains:
        When True, evidence triggers can activate a domain even if routing missed it.
        This is useful as a safety net: a cabling case that got misrouted should still
        get cabling completeness warnings.
    """
    rulebook = dict(rules or load_sow_rules())
    corpus = CorpusView.build(atoms=atoms, packets=packets, site_clusters=site_clusters)

    active = _canonical_pack_ids(selected_pack_ids, rulebook)
    if infer_domains:
        active |= _infer_domains_from_evidence(corpus, rulebook)
    domains_def_all = rulebook.get("domains") or {}
    active = {d for d in active if d in domains_def_all}

    # v9: a CONFIDENT service-router head overrides the pack-prior over-selection +
    # evidence inference. Restrict the active set to the routed primary (+ secondary
    # + always-on infra) so a confident audio_visual deal stops running
    # msp/datacenter/cabling checklists (the 29 phantom gaps). The required-anchor
    # gate below still applies. When the head abstains / scores < TAU we keep the
    # union (the infer-domains safety net for genuinely misrouted cases).
    sr_primary, sr_conf = _router_primary(service_routing)
    trusted_primary = (
        sr_primary
        if sr_primary and sr_primary in domains_def_all and sr_conf >= _ROUTER_TRUST_TAU
        else None
    )
    if trusted_primary:
        secondary = {
            str(s).strip()
            for s in ((service_routing or {}).get("secondary") or [])
            if str(s).strip()
        }
        keep = {trusted_primary} | secondary | (_ALWAYS_ON_DOMAINS & active)
        active = {d for d in keep if d in domains_def_all}

    # Boss-review v8 F6/F8 — the router can over-select packs (e.g.
    # ``wireless`` and ``audio_visual`` for a cabling-only case
    # because of incidental keyword matches). Apply the same
    # ``required_anchor_regex_any`` gate to ROUTER-selected domains,
    # not just inferred ones, so wireless rules don't run on a
    # cabling case that only happens to mention "Aruba" once.
    #
    # v9 trusted the neural primary enough to skip this gate. That let a
    # mis-embedded UPS/APC battery install (Stinson) keep wireless active
    # at 0.92 confidence with zero WLAN anchors and flood RED blockers.
    # parser-os now also evidence-gates the head; Orbit still enforces the
    # pack anchors here as defense-in-depth — a confident wrong primary
    # without anchors is dropped, not trusted.
    domains_def = rulebook.get("domains") or {}
    active = {
        d for d in active
        if _domain_required_anchor_satisfied(d, domains_def.get(d) or {}, corpus)
    }

    checks_to_run: list[tuple[str, Mapping[str, Any]]] = []
    if include_global:
        for check in rulebook.get("global_checks") or []:
            checks_to_run.append(("global", check))
    for domain_id in sorted(active):
        for check in (rulebook.get("domains") or {}).get(domain_id, {}).get("checks") or []:
            checks_to_run.append((domain_id, check))

    findings: list[SowCompletenessFinding] = []
    satisfied_count = 0

    for domain_id, check in checks_to_run:
        satisfied, observed = _check_satisfied(check, corpus)
        if satisfied:
            satisfied_count += 1
            continue
        severity = str(check.get("severity") or "warning")
        findings.append(
            SowCompletenessFinding(
                rule_id=str(check.get("id") or f"{domain_id}.unnamed_check"),
                domain_id=domain_id,
                label=str(check.get("label") or check.get("id") or "Unnamed check"),
                severity=severity,
                message=str(check.get("message") or "SOW completeness evidence missing."),
                suggested_open_question=str(
                    check.get("suggested_open_question")
                    or "Confirm the missing SOW detail before publish."
                ),
                evidence_searched=dict(check.get("evidence") or {}),
                observed_support=observed,
            )
        )

    quote_delivery_model = _parser_quote_delivery_model(corpus.atoms)
    suppressed_by_quote_context = 0
    if quote_delivery_model == "config_only":
        before = len(findings)
        findings = [f for f in findings if f.rule_id not in _CONFIG_ONLY_WIRELESS_GAP_IDS]
        suppressed_by_quote_context = before - len(findings)

    suppressed_by_network_install = 0
    if _corpus_has_network_install(corpus):
        before = len(findings)
        findings = [f for f in findings if f.rule_id not in _NETWORK_INSTALL_OPS_GAP_IDS]
        suppressed_by_network_install = before - len(findings)

    coverage = {
        "checks_run": len(checks_to_run),
        "checks_satisfied": satisfied_count,
        "checks_missing": len(findings),
        "atoms_seen": len(corpus.atoms),
        "packets_seen": len(corpus.packets),
        "site_clusters_seen": len(corpus.site_clusters),
        "quote_context_suppressed": suppressed_by_quote_context,
        "network_install_ops_suppressed": suppressed_by_network_install,
    }

    return SowCompletenessResult(
        status=_severity_status(findings),
        active_domain_ids=tuple(sorted(active)),
        findings=tuple(findings),
        coverage=coverage,
    )


def evaluate_from_case_payloads(
    *,
    envelope: Mapping[str, Any] | None = None,
    pack_prior: Mapping[str, Any] | None = None,
    site_reality: Mapping[str, Any] | None = None,
    rules: Mapping[str, Any] | None = None,
    infer_domains: bool = True,
) -> SowCompletenessResult:
    """Convenience adapter for files emitted by compile_corpus.py."""
    envelope = envelope or {}
    pack_prior = pack_prior or {}
    site_reality = site_reality or {}
    selected = list(pack_prior.get("selected_pack_ids") or [])
    top = pack_prior.get("top_pack_id")
    if top and top not in selected:
        selected.insert(0, str(top))
    return evaluate_sow_completeness(
        selected_pack_ids=selected,
        atoms=envelope.get("atoms") or [],
        packets=envelope.get("packets") or [],
        site_clusters=site_reality.get("clusters") or [],
        rules=rules,
        infer_domains=infer_domains,
        service_routing=envelope.get("service_routing"),
    )
