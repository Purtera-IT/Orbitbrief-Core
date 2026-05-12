from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

NARRATIVE_CLAIM_ONTOLOGY_VERSION = "1.0.0"

NARRATIVE_CLAIM_FAMILIES: dict[str, str] = {
    "project_identity": "Project naming and identity fields.",
    "customer_identity": "Customer and end-customer naming fields.",
    "request_context": "Request source and intake context.",
    "business_driver": "Business motivation and success intent.",
    "project_summary": "High-level narrative project description.",
    "success_criteria": "Explicit completion outcomes.",
    "site_count_claim": "Explicit or strongly supported site count.",
    "site_location_claim": "Site location names, addresses, and geography.",
    "site_type_claim": "Site type and profile labels.",
    "site_topology_claim": "Building/floor/MDF/IDF/topology references.",
    "site_condition_claim": "Observed site conditions and constraints.",
    "scope_included_claim": "In-scope tasks and workstream items.",
    "scope_excluded_claim": "Out-of-scope statements.",
    "scope_by_others_claim": "By-others ownership statements.",
    "known_quantity_claim": "Quantities and units.",
    "technical_environment_claim": "Current/target technical environment and dependencies.",
    "schedule_claim": "Dates, milestones, cutover, blackout windows.",
    "access_logistics_claim": "Access constraints and logistics conditions.",
    "drawing_metadata_claim": "Drawing sheet metadata and title-block context.",
    "network_room_claim": "MDF/IDF/closet/network-room references from drawings.",
    "equipment_reference_claim": "Equipment labels and bounded quantity-style references from drawings.",
    "scope_note_claim": "Drawing note-scope hints bounded to local packet evidence.",
    "constructability_claim": "Constructability and readiness constraints from drawing packets.",
    "revision_change_claim": "Revision/change indicators from drawing revision packets.",
    "topology_hint_claim": "Low-confidence topology neighborhood hints from drawings.",
    "deliverable_claim": "Deliverables and output artifacts.",
    "testing_acceptance_claim": "Testing requirements and acceptance basis.",
    "customer_responsibility_claim": "Customer-owned tasks and responsibilities.",
    "customer_input_required_claim": "Inputs customer must provide.",
    "customer_document_required_claim": "Required customer docs.",
    "customer_material_claim": "Customer-provided materials/equipment.",
    "third_party_dependency_claim": "External dependency constraints.",
    "commercial_structure_claim": "Commercial model and billing constraints.",
    "assumption_claim": "Assumptions and prerequisite conditions.",
    "risk_claim": "Risk statements and uncertainty signals.",
    "open_question_claim": "Questions needing resolution.",
    "readiness_gap_claim": "Readiness blockers and gaps.",
    "contact_claim": "Primary customer contact details.",
    "decision_maker_claim": "Decision-maker references.",
    "sow_author_note_claim": "Author guidance notes for final SOW drafting.",
}


NARRATIVE_CLAIM_STATUS_VALUES: tuple[str, ...] = (
    "asserted",
    "possible",
    "ambiguous",
    "needs_review",
)


ClaimStatus = Literal["asserted", "possible", "ambiguous", "needs_review"]
ClaimFamily = Literal[
    "scope_included_claim",
    "scope_excluded_claim",
    "assumption_claim",
    "risk_claim",
    "third_party_dependency_claim",
    "site_location_claim",
    "known_quantity_claim",
    "deliverable_claim",
    "schedule_claim",
    "customer_responsibility_claim",
    "open_question_claim",
]


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    span_id: str
    role: Literal["anchor", "support", "context"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "span_id": self.span_id,
            "role": self.role,
        }


@dataclass(frozen=True, slots=True)
class EvidenceRefSet:
    packet_id: str
    primary_span_id: str
    supporting_span_ids: tuple[str, ...]
    all_span_ids: tuple[str, ...]
    refs: tuple[EvidenceRef, ...]

    def __post_init__(self) -> None:
        if not self.primary_span_id:
            raise ValueError("EvidenceRefSet.primary_span_id is required")
        if not self.all_span_ids:
            raise ValueError("EvidenceRefSet.all_span_ids must be non-empty")
        if self.primary_span_id not in self.all_span_ids:
            raise ValueError("EvidenceRefSet.primary_span_id must be included in all_span_ids")
        if not self.refs:
            raise ValueError("EvidenceRefSet.refs must be non-empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "packet_id": self.packet_id,
            "primary_span_id": self.primary_span_id,
            "supporting_span_ids": list(self.supporting_span_ids),
            "all_span_ids": list(self.all_span_ids),
            "refs": [ref.to_dict() for ref in self.refs],
        }


@dataclass(frozen=True, slots=True)
class InternalClaim:
    claim_id: str
    claim_family: ClaimFamily
    packet_id: str
    packet_family: str
    claim_body: str
    confidence: float
    status: ClaimStatus
    verification_needed: bool
    stronger_source_needed: bool
    evidence: EvidenceRefSet
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.confidence < 0.0 or self.confidence > 1.0:
            raise ValueError("InternalClaim.confidence must be in [0.0, 1.0]")
        if self.status not in NARRATIVE_CLAIM_STATUS_VALUES:
            raise ValueError(f"Unsupported claim status: {self.status!r}")
        if not self.claim_body.strip():
            raise ValueError("InternalClaim.claim_body must be non-empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "claim_family": self.claim_family,
            "packet_id": self.packet_id,
            "packet_family": self.packet_family,
            "claim_body": self.claim_body,
            "confidence": self.confidence,
            "status": self.status,
            "verification_needed": self.verification_needed,
            "stronger_source_needed": self.stronger_source_needed,
            "evidence": self.evidence.to_dict(),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class ExtractionDiagnostic:
    code: str
    message: str
    packet_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "packet_id": self.packet_id,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class FieldClaim:
    claim_family: ClaimFamily
    field_path: str
    value: Any
    source_claim_id: str
    evidence: EvidenceRefSet
    confidence: float
    status: ClaimStatus
    projection_reason_codes: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.confidence < 0.0 or self.confidence > 1.0:
            raise ValueError("FieldClaim.confidence must be in [0.0, 1.0]")
        if not self.field_path.strip():
            raise ValueError("FieldClaim.field_path must be non-empty")
        if not self.source_claim_id.strip():
            raise ValueError("FieldClaim.source_claim_id must be non-empty")
        if self.status not in NARRATIVE_CLAIM_STATUS_VALUES:
            raise ValueError(f"Unsupported field-claim status: {self.status!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_family": self.claim_family,
            "field_path": self.field_path,
            "value": self.value,
            "source_claim_id": self.source_claim_id,
            "evidence": self.evidence.to_dict(),
            "confidence": self.confidence,
            "status": self.status,
            "projection_reason_codes": list(self.projection_reason_codes),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class NarrativeExtractionResult:
    internal_claims: tuple[InternalClaim, ...]
    field_claims: tuple[FieldClaim, ...]
    extraction_diagnostics: tuple[ExtractionDiagnostic, ...]
    review_flags: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "internal_claims": [claim.to_dict() for claim in self.internal_claims],
            "field_claims": [claim.to_dict() for claim in self.field_claims],
            "extraction_diagnostics": [diag.to_dict() for diag in self.extraction_diagnostics],
            "review_flags": list(self.review_flags),
        }
