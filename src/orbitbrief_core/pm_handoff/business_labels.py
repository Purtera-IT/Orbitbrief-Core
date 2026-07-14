from __future__ import annotations

import re
from typing import Any

DOMAIN_LABELS: dict[str, str] = {
    "alm": "Application / lifecycle management",
    "audit": "Audit / compliance",
    "audio_visual": "Audio visual / low-voltage AV",
    "building_management_systems": "Building management systems",
    "camera_vms_operations": "Camera / VMS operations",
    "commercial": "Commercial terms",
    "das": "DAS / cellular / public-safety radio",
    "datacenter": "Datacenter / rack-and-stack",
    "network_edge_install": "Network edge install",
    "project": "Project",
    "delivery_execution": "Delivery / execution planning",
    "electrical": "Electrical / power",
    "fire_safety": "Fire safety",
    "hardware": "Hardware / equipment",
    "imac": "IMAC / moves-adds-changes",
    "itad": "IT asset disposal",
    "low_voltage_cabling": "Structured cabling",
    "msp": "Managed services / NOC / SOC",
    "network_maintenance": "Network maintenance / operations",
    "paging_mass_notification": "Paging / mass notification",
    "procurement_finance": "Procurement / finance",
    "professional_services": "Professional services",
    "rack_and_stack": "Rack-and-stack",
    "security_access": "Security access control",
    "security_camera": "Security camera / VMS",
    "site_structure": "Sites / facilities",
    "staff_augmentation": "Staff augmentation",
    "telecom": "Telecom / carrier",
    "wireless": "Wireless / WLAN",
    "other": "Other / unclassified",
}

FACT_CATEGORY_LABELS: dict[str, str] = {
    "sites": "Sites, access, and facilities",
    "scope": "Scope and deliverables",
    "schedule": "Schedule, phases, and milestones",
    "stakeholders": "Stakeholders, approvers, and signatories",
    "commercial": "Commercial terms, payment, and approvals",
    "bom": "BOM, procurement, and pricing",
    "assets": "Asset inventory",
    "network": "Network, ports, VLANs, and circuits",
    "msp_ops": "Managed-services operations",
    "acceptance": "Acceptance, validation, cutover, and runbooks",
    "compliance": "Compliance, classification, and data handling",
    "integration": "Integration checkpoints and system mappings",
    "risks": "Risks, assumptions, and constraints",
    "exclusions": "Exclusions and commercial boundaries",
    "forms": "Form selections and field states",
}

CATEGORY_ORDER = [
    "sites",
    "stakeholders",
    "schedule",
    "scope",
    "bom",
    "commercial",
    "assets",
    "network",
    "msp_ops",
    "acceptance",
    "compliance",
    "integration",
    "risks",
    "exclusions",
    "forms",
]

SEVERITY_SORT = {"blocker": 0, "warning": 1, "info": 2}

SA_FOCUS_BY_DOMAIN: dict[str, list[str]] = {
    "low_voltage_cabling": [
        "Validate cable category, jacket rating, termination scheme, labeling standard, and test report requirement.",
        "Confirm pathway ownership, firestopping, rough-in / trim-out split, and MDF/IDF cable-management standard.",
        "Validate patch panels, faceplates, jacks, service loops, grounding/bonding, and closeout package requirements.",
    ],
    "wireless": [
        "Validate AP model/count, per-AP PoE class, cable certification level, mounting heights, and survey/post-validation expectations.",
        "Confirm SSID/VLAN/auth matrix, DFS/WIPS policy, device onboarding workflow, and E-rate/owner-furnished boundaries if applicable.",
    ],
    "msp": [
        "Validate service tier, SLA targets, escalation path, tooling ownership, onboarding milestones, and reporting cadence.",
        "Confirm customer responsibilities, remote access, PAM/JIT admin, backup/DR/RTO/RPO, and exit/transition clauses.",
    ],
    "network_maintenance": [
        "Validate device inventory, firmware gold image, patch cadence, OEM TAC entitlement, circuit demarcation, VLAN/port audit scope, and change calendar.",
    ],
    "security_camera": [
        "Validate camera count/model/type, VMS platform, retention, recording mode, storage/NVR sizing, privacy masks, and acceptance testing.",
    ],
    "audio_visual": [
        "Validate room list, display/camera/mic/DSP/control/UC platform, programming hours, commissioning, and acceptance criteria.",
    ],
    "electrical": [
        "Validate panel/circuit/receptacle/UPS/generator/grounding details and electrical exclusion boundaries.",
    ],
}


def domain_label(domain_id: str) -> str:
    return DOMAIN_LABELS.get(domain_id, domain_id.replace("_", " ").title())


def severity_label(severity: str) -> str:
    return {
        "blocker": "Must resolve before SOW",
        "warning": "PM review / clarification",
        "info": "Nice-to-have / polish",
    }.get(severity, severity.title())


def normalize_for_dedupe(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def compact_text(text: Any, max_chars: int = 360) -> str:
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 1].rstrip() + "…"


def classify_fact_category(atom_type: str, text: str) -> str:
    t = f"{atom_type} {text}".lower()

    # Prioritize explicit structured evidence types before keyword fallbacks.
    if atom_type == "site_roster":
        return "sites"
    if atom_type in {"asset_record", "lifecycle_status"}:
        return "assets"
    if atom_type in {"port_vlan_assignment", "circuit_inventory"}:
        return "network"
    if atom_type in {"support_entitlement", "alert_route"}:
        return "msp_ops"
    if atom_type in {"cutover_validation", "action_item", "rfi_row", "runbook_row", "working_measurement_row", "workflow_step"}:
        return "acceptance"
    if atom_type in {"vendor_line_item", "quantity"}:
        return "bom"
    if atom_type in {"risk", "assumption", "constraint"}:
        return "risks"
    if atom_type in {"exclusion", "conditional_support_boundary"}:
        return "exclusions"
    if atom_type == "form_option_state":
        return "forms"

    # v47 — universal deal-packet taxonomy routes
    if atom_type in {
        "physical_site",
        "site_attribute",
        "site_access_window",
        "site_access_restriction",
        "site_infrastructure",
        "site_room_mix",
        "site_implementation_note",
    }:
        return "sites"
    if atom_type in {
        "milestone_phase",
        "task",
        "deliverable",
        "cutover_step",
        "blackout_date_range",
    }:
        return "schedule"
    if atom_type in {
        "stakeholder",
        "approval_authority",
        "approval_decision",
        "signatory",
    }:
        return "stakeholders"
    if atom_type in {
        "bom_line",
        "site_allocation",
        "service_line",
        "site_budget",
        "lead_time_constraint",
        "pricing_assumption",
    }:
        return "bom"
    if atom_type in {
        "deal_metadata",
        "commercial_total",
        "payment_term",
        "change_order_rule",
    }:
        return "commercial"
    if atom_type in {
        "requirement",
        "acceptance_criterion",
        "electrical_acceptance_test",
    }:
        return "acceptance"
    if atom_type in {
        "compliance_classification",
        "compliance_rule",
    }:
        return "compliance"
    if atom_type in {
        "mitigation",
        "dependency",
    }:
        return "risks"
    if atom_type in {
        "data_flow_step",
        "system_mapping",
        "metadata_requirement",
        "integration_checkpoint",
    }:
        return "integration"

    # Keyword fallbacks for less-typed evidence.
    if any(x in t for x in ["address:", "site id", "mdf", "idf", "access"]):
        return "sites"
    if any(x in t for x in ["asset id", "hostname", "serial"]):
        return "assets"
    if any(x in t for x in ["vlan", "port:", "circuit", "provider"]):
        return "network"
    if any(x in t for x in ["sla", "noc", "soc", "runbook", "ticket", "monitor"]):
        return "msp_ops"
    if any(x in t for x in ["sku", "bom", "unit cost", "lead time", "quote"]):
        return "bom"
    if any(x in t for x in ["risk", "assumption", "blocked", "pending", "constraint"]):
        return "risks"
    if any(x in t for x in ["excluded", "out of scope", "not included"]):
        return "exclusions"
    if any(x in t for x in ["selected", "not selected", "checkbox", "form option"]):
        return "forms"
    if any(x in t for x in ["validation", "acceptance", "cutover", "workflow step"]):
        return "acceptance"
    return "scope"
