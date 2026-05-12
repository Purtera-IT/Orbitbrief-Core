from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Mapping

PARSER_IR_VERSION = "v1"


# -----------------------------
# Enums and scalar helper types
# -----------------------------


class ContainerType(str, Enum):
    TEXT = "text"
    EMAIL = "email"
    DOCUMENT = "document"
    PDF = "pdf"
    NOTES = "notes"


class DiscourseType(str, Enum):
    CALL_TRANSCRIPT = "call_transcript"
    MEETING_NOTES = "meeting_notes"
    EMAIL_THREAD = "email_thread"
    PROJECT_MEMO = "project_memo"
    HYBRID_NOTES_MEMO = "hybrid_notes_memo"


class SourceLayer(str, Enum):
    RAW = "raw"
    NORMALIZED = "normalized"
    OCR = "ocr"
    ENRICHED = "enriched"


class ReviewSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    HIGH = "high"


class ReviewCategory(str, Enum):
    AMBIGUITY = "ambiguity"
    CONTRADICTION = "contradiction"
    MISSING_EVIDENCE = "missing_evidence"
    AUTHORITY_GAP = "authority_gap"
    BOUNDARY_RISK = "boundary_risk"
    QUALITY = "quality"


class AuthorityClass(str, Enum):
    FIRST_PASS = "first_pass"
    VERIFIED = "verified"
    AUTHORITATIVE = "authoritative"
    UNKNOWN = "unknown"


class EvidenceKind(str, Enum):
    FACT = "fact"
    CLAIM = "claim"
    QUOTE = "quote"
    HINT = "hint"
    NEGATIVE = "negative"


class RelationType(str, Enum):
    REFERENCES = "references"
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    FOLLOWS = "follows"
    REPLIES_TO = "replies_to"
    SAME_AS = "same_as"


class PacketKind(str, Enum):
    FIELD = "field"
    CLAIM = "claim"
    REVIEW = "review"
    ROUTING = "routing"


class CueKind(str, Enum):
    HEDGE = "hedge"
    COMMITMENT = "commitment"
    UNCERTAINTY = "uncertainty"
    NEGATION = "negation"
    QUANTITY = "quantity"
    SCHEDULE = "schedule"


class NodeKind(str, Enum):
    ACTOR = "actor"
    SECTION = "section"
    MESSAGE = "message"
    TIME_ANCHOR = "time_anchor"
    EVIDENCE = "evidence"
    PACKET = "packet"
    DOCUMENT = "document"


class RegionKind(str, Enum):
    TITLE_BLOCK = "title_block"
    REVISION_BLOCK = "revision_block"
    NOTE_BLOCK = "note_block"
    CALLOUT = "callout"
    ROOM_LABEL = "room_label"
    CLOSET_LABEL = "closet_label"
    EQUIPMENT_LABEL = "equipment_label"
    DIMENSION_TEXT = "dimension_text"
    LEGEND = "legend"
    UNKNOWN = "unknown"


class DrawingKind(str, Enum):
    FLOORPLAN = "floorplan"
    RACK_DIAGRAM = "rack_diagram"
    ONE_LINE = "one_line"
    WIRELESS_LAYOUT = "wireless_layout"
    ELEVATION = "elevation"
    UNKNOWN = "unknown"


class ComponentKind(str, Enum):
    AP = "ap"
    RACK = "rack"
    SWITCH = "switch"
    PANEL = "panel"
    CABINET = "cabinet"
    PRINTER = "printer"
    CONFERENCE_ROOM = "conference_room"
    WORKSTATION_AREA = "workstation_area"
    UNKNOWN = "unknown"


class RelationHintKind(str, Enum):
    INSIDE_ZONE = "inside_zone"
    NEAR = "near"
    CALLOUT_FOR = "callout_for"
    NOTE_ATTACHED_TO = "note_attached_to"
    SAME_REVISION_BLOCK = "same_revision_block"
    SAME_TITLE_BLOCK = "same_title_block"
    COMPONENT_IN_ZONE = "component_in_zone"
    POSSIBLE_TOPOLOGY_NEIGHBOR = "possible_topology_neighbor"


@dataclass(frozen=True, slots=True)
class CharRange:
    start: int
    end: int

    def __post_init__(self) -> None:
        if self.start < 0:
            raise ValueError("CharRange.start must be >= 0")
        if self.end < self.start:
            raise ValueError("CharRange.end must be >= start")


@dataclass(frozen=True, slots=True)
class BBox:
    x0: float
    y0: float
    x1: float
    y1: float
    page_index: int | None = None
    units: str | None = None

    def __post_init__(self) -> None:
        if self.x1 < self.x0 or self.y1 < self.y0:
            raise ValueError("BBox max coordinates must be >= min coordinates")


@dataclass(frozen=True, slots=True)
class PageRef:
    page_index: int
    page_label: str | None = None
    source_uri: str | None = None


@dataclass(frozen=True, slots=True)
class VisualRegion:
    region_id: str
    sheet_id: str
    region_kind: RegionKind = RegionKind.UNKNOWN
    page_ref: PageRef | None = None
    page_index: int | None = None
    bbox: BBox | None = None
    raw_text: str = ""
    normalized_text: str = ""
    source_ref: str | None = None
    parent_region_id: str | None = None
    zone_id: str | None = None
    nearby_region_ids: tuple[str, ...] = ()
    source_span_ids: tuple[str, ...] = ()
    confidence: float = 0.0
    review_flag_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.confidence < 0.0 or self.confidence > 1.0:
            raise ValueError("VisualRegion.confidence must be in [0.0, 1.0]")

    def to_dict(self) -> dict[str, Any]:
        return {
            "region_id": self.region_id,
            "sheet_id": self.sheet_id,
            "region_kind": self.region_kind.value,
            "page_ref": asdict(self.page_ref) if self.page_ref is not None else None,
            "page_index": self.page_index,
            "bbox": asdict(self.bbox) if self.bbox is not None else None,
            "raw_text": self.raw_text,
            "normalized_text": self.normalized_text,
            "source_ref": self.source_ref,
            "parent_region_id": self.parent_region_id,
            "zone_id": self.zone_id,
            "nearby_region_ids": list(self.nearby_region_ids),
            "source_span_ids": list(self.source_span_ids),
            "confidence": self.confidence,
            "review_flag_ids": list(self.review_flag_ids),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class SheetRef:
    sheet_id: str
    sheet_number: str | None = None
    sheet_title: str | None = None
    drawing_kind: DrawingKind = DrawingKind.UNKNOWN
    page_ref: PageRef | None = None
    page_index: int | None = None
    source_ref: str | None = None
    confidence: float = 0.0
    review_flag_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.confidence < 0.0 or self.confidence > 1.0:
            raise ValueError("SheetRef.confidence must be in [0.0, 1.0]")

    def to_dict(self) -> dict[str, Any]:
        return {
            "sheet_id": self.sheet_id,
            "sheet_number": self.sheet_number,
            "sheet_title": self.sheet_title,
            "drawing_kind": self.drawing_kind.value,
            "page_ref": asdict(self.page_ref) if self.page_ref is not None else None,
            "page_index": self.page_index,
            "source_ref": self.source_ref,
            "confidence": self.confidence,
            "review_flag_ids": list(self.review_flag_ids),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class TitleBlockField:
    field_name: str
    field_value: str
    sheet_id: str = ""
    page_index: int | None = None
    bbox: BBox | None = None
    raw_text: str = ""
    normalized_text: str = ""
    source_ref: str | None = None
    region_id: str | None = None
    confidence: float = 0.0
    review_flag_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.confidence < 0.0 or self.confidence > 1.0:
            raise ValueError("TitleBlockField.confidence must be in [0.0, 1.0]")

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_name": self.field_name,
            "field_value": self.field_value,
            "sheet_id": self.sheet_id,
            "page_index": self.page_index,
            "bbox": asdict(self.bbox) if self.bbox is not None else None,
            "raw_text": self.raw_text,
            "normalized_text": self.normalized_text,
            "source_ref": self.source_ref,
            "region_id": self.region_id,
            "confidence": self.confidence,
            "review_flag_ids": list(self.review_flag_ids),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class RevisionEntry:
    revision_code: str
    revision_note: str
    revision_id: str = ""
    sheet_id: str = ""
    revision_date: str | None = None
    page_index: int | None = None
    bbox: BBox | None = None
    source_ref: str | None = None
    region_id: str | None = None
    confidence: float = 0.0
    review_flag_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.confidence < 0.0 or self.confidence > 1.0:
            raise ValueError("RevisionEntry.confidence must be in [0.0, 1.0]")

    def to_dict(self) -> dict[str, Any]:
        return {
            "revision_id": self.revision_id,
            "sheet_id": self.sheet_id,
            "revision_code": self.revision_code,
            "revision_note": self.revision_note,
            "revision_date": self.revision_date,
            "page_index": self.page_index,
            "bbox": asdict(self.bbox) if self.bbox is not None else None,
            "source_ref": self.source_ref,
            "region_id": self.region_id,
            "confidence": self.confidence,
            "review_flag_ids": list(self.review_flag_ids),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class CalloutRef:
    callout_id: str
    label: str
    sheet_id: str = ""
    page_index: int | None = None
    bbox: BBox | None = None
    source_ref: str | None = None
    region_id: str | None = None
    target_region_id: str | None = None
    confidence: float = 0.0
    review_flag_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.confidence < 0.0 or self.confidence > 1.0:
            raise ValueError("CalloutRef.confidence must be in [0.0, 1.0]")

    def to_dict(self) -> dict[str, Any]:
        return {
            "callout_id": self.callout_id,
            "sheet_id": self.sheet_id,
            "label": self.label,
            "page_index": self.page_index,
            "bbox": asdict(self.bbox) if self.bbox is not None else None,
            "source_ref": self.source_ref,
            "region_id": self.region_id,
            "target_region_id": self.target_region_id,
            "confidence": self.confidence,
            "review_flag_ids": list(self.review_flag_ids),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class ComponentLabel:
    component_id: str
    label: str
    sheet_id: str = ""
    component_kind: ComponentKind = ComponentKind.UNKNOWN
    page_index: int | None = None
    bbox: BBox | None = None
    raw_text: str = ""
    normalized_text: str = ""
    source_ref: str | None = None
    region_id: str | None = None
    zone_id: str | None = None
    confidence: float = 0.0
    review_flag_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.confidence < 0.0 or self.confidence > 1.0:
            raise ValueError("ComponentLabel.confidence must be in [0.0, 1.0]")

    def to_dict(self) -> dict[str, Any]:
        return {
            "component_id": self.component_id,
            "sheet_id": self.sheet_id,
            "label": self.label,
            "component_kind": self.component_kind.value,
            "page_index": self.page_index,
            "bbox": asdict(self.bbox) if self.bbox is not None else None,
            "raw_text": self.raw_text,
            "normalized_text": self.normalized_text,
            "source_ref": self.source_ref,
            "region_id": self.region_id,
            "zone_id": self.zone_id,
            "confidence": self.confidence,
            "review_flag_ids": list(self.review_flag_ids),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class SpatialZone:
    zone_id: str
    zone_name: str
    sheet_id: str = ""
    zone_kind: RegionKind = RegionKind.UNKNOWN
    page_index: int | None = None
    bbox: BBox | None = None
    source_ref: str | None = None
    region_ids: tuple[str, ...] = ()
    confidence: float = 0.0
    review_flag_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.confidence < 0.0 or self.confidence > 1.0:
            raise ValueError("SpatialZone.confidence must be in [0.0, 1.0]")

    def to_dict(self) -> dict[str, Any]:
        return {
            "zone_id": self.zone_id,
            "sheet_id": self.sheet_id,
            "zone_name": self.zone_name,
            "zone_kind": self.zone_kind.value,
            "page_index": self.page_index,
            "bbox": asdict(self.bbox) if self.bbox is not None else None,
            "source_ref": self.source_ref,
            "region_ids": list(self.region_ids),
            "confidence": self.confidence,
            "review_flag_ids": list(self.review_flag_ids),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class DiagramRelationHint:
    hint_id: str
    sheet_id: str
    source_region_id: str
    target_region_id: str
    relation_kind: RelationHintKind = RelationHintKind.NEAR
    confidence: float = 0.0
    reason: str = ""
    source_ref: str | None = None
    review_flag_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.confidence < 0.0 or self.confidence > 1.0:
            raise ValueError("DiagramRelationHint.confidence must be in [0.0, 1.0]")

    def to_dict(self) -> dict[str, Any]:
        return {
            "hint_id": self.hint_id,
            "sheet_id": self.sheet_id,
            "source_region_id": self.source_region_id,
            "target_region_id": self.target_region_id,
            "relation_kind": self.relation_kind.value,
            "confidence": self.confidence,
            "reason": self.reason,
            "source_ref": self.source_ref,
            "review_flag_ids": list(self.review_flag_ids),
            "metadata": dict(self.metadata),
        }


# -----------------------------
# Review and evidence objects
# -----------------------------


@dataclass(frozen=True, slots=True)
class ReviewFlag:
    flag_id: str
    severity: ReviewSeverity
    category: ReviewCategory
    message: str
    span_id: str | None = None
    claim_id: str | None = None
    field_path: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class EvidenceSpan:
    span_id: str
    text: str
    normalized_text: str
    doc_id: str
    container_type: ContainerType
    discourse_type: DiscourseType
    page_ref: PageRef | None = None
    bbox: BBox | None = None
    char_range: CharRange | None = None
    section_path: tuple[str, ...] = ()
    speaker_id: str | None = None
    author_id: str | None = None
    message_id: str | None = None
    time_anchor_id: str | None = None
    chronology_rank: int | None = None
    authority_score: float = 0.0
    source_layer: SourceLayer = SourceLayer.NORMALIZED
    review_flag_ids: tuple[str, ...] = ()
    evidence_kind: EvidenceKind = EvidenceKind.FACT
    authority_class: AuthorityClass = AuthorityClass.UNKNOWN
    cue_kinds: tuple[CueKind, ...] = ()
    previous_span_id: str | None = None
    next_span_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.authority_score < 0.0 or self.authority_score > 1.0:
            raise ValueError("EvidenceSpan.authority_score must be in [0.0, 1.0]")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# -----------------------------
# Graph and structure objects
# -----------------------------


@dataclass(frozen=True, slots=True)
class ActorNode:
    actor_id: str
    node_kind: NodeKind = NodeKind.ACTOR
    display_name: str | None = None
    role_label: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ActorEdge:
    source_actor_id: str
    target_actor_id: str
    relation_type: RelationType
    weight: float = 1.0
    evidence_span_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ActorGraph:
    nodes: tuple[ActorNode, ...] = ()
    edges: tuple[ActorEdge, ...] = ()
    primary_actor_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SectionNode:
    section_id: str
    title: str | None = None
    section_path: tuple[str, ...] = ()
    parent_section_id: str | None = None
    child_section_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SectionTree:
    nodes: tuple[SectionNode, ...] = ()
    root_section_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MessageNode:
    message_id: str
    thread_id: str | None = None
    author_id: str | None = None
    speaker_id: str | None = None
    section_id: str | None = None
    span_ids: tuple[str, ...] = ()
    time_anchor_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ThreadEdge:
    source_message_id: str
    target_message_id: str
    relation_type: RelationType = RelationType.REPLIES_TO
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ThreadGraph:
    thread_id: str
    message_nodes: tuple[MessageNode, ...] = ()
    edges: tuple[ThreadEdge, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TimeAnchor:
    time_anchor_id: str
    label: str
    iso8601: str | None = None
    epoch_ms: int | None = None
    sequence_rank: int | None = None
    is_inferred: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ChronologyEdge:
    source_time_anchor_id: str
    target_time_anchor_id: str
    relation_type: RelationType = RelationType.FOLLOWS
    confidence: float = 1.0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.confidence < 0.0 or self.confidence > 1.0:
            raise ValueError("ChronologyEdge.confidence must be in [0.0, 1.0]")


@dataclass(frozen=True, slots=True)
class ChronologyGraph:
    time_anchors: tuple[TimeAnchor, ...] = ()
    edges: tuple[ChronologyEdge, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EvidenceEdge:
    source_span_id: str
    target_span_id: str
    relation_type: RelationType
    weight: float = 1.0
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EvidenceGraph:
    edges: tuple[EvidenceEdge, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


# -----------------------------
# Extractor-facing packet model
# -----------------------------


@dataclass(frozen=True, slots=True)
class PacketCandidate:
    packet_id: str
    packet_kind: PacketKind
    span_ids: tuple[str, ...]
    primary_span_id: str | None = None
    target_field_paths: tuple[str, ...] = ()
    target_claim_family_names: tuple[str, ...] = ()
    confidence: float = 0.0
    authority_class: AuthorityClass = AuthorityClass.UNKNOWN
    evidence_kind: EvidenceKind = EvidenceKind.CLAIM
    review_flag_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.confidence < 0.0 or self.confidence > 1.0:
            raise ValueError("PacketCandidate.confidence must be in [0.0, 1.0]")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# -----------------------------
# Top-level parser result
# -----------------------------


@dataclass(frozen=True, slots=True)
class DocumentParse:
    doc_id: str
    pack_id: str
    role_id: str
    modality: str
    container_type: ContainerType
    discourse_type: DiscourseType
    source_layer: SourceLayer
    evidence_spans: tuple[EvidenceSpan, ...] = ()
    review_flags: tuple[ReviewFlag, ...] = ()
    actor_graph: ActorGraph = field(default_factory=ActorGraph)
    section_tree: SectionTree = field(default_factory=SectionTree)
    thread_graph: ThreadGraph | None = None
    chronology_graph: ChronologyGraph = field(default_factory=ChronologyGraph)
    evidence_graph: EvidenceGraph = field(default_factory=EvidenceGraph)
    packet_candidates: tuple[PacketCandidate, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ParseInvariantError(ValueError):
    """Raised when a parse object graph violates hard invariants."""


def _flag(
    index: int,
    *,
    severity: ReviewSeverity,
    category: ReviewCategory,
    message: str,
    span_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> ReviewFlag:
    return ReviewFlag(
        flag_id=f"validation:{index:04d}",
        severity=severity,
        category=category,
        message=message,
        span_id=span_id,
        metadata=metadata or {},
    )


def validate_document_parse(parse: DocumentParse) -> list[ReviewFlag]:
    issues: list[ReviewFlag] = []

    def add(
        severity: ReviewSeverity,
        category: ReviewCategory,
        message: str,
        *,
        span_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        issues.append(
            _flag(
                len(issues) + 1,
                severity=severity,
                category=category,
                message=message,
                span_id=span_id,
                metadata=metadata,
            )
        )

    span_ids = [span.span_id for span in parse.evidence_spans]
    flag_ids = [flag.flag_id for flag in parse.review_flags]
    actor_ids = [node.actor_id for node in parse.actor_graph.nodes]
    section_ids = [node.section_id for node in parse.section_tree.nodes]
    packet_ids = [packet.packet_id for packet in parse.packet_candidates]
    message_ids: list[str] = [node.message_id for node in parse.thread_graph.message_nodes] if parse.thread_graph else []
    time_anchor_ids = [anchor.time_anchor_id for anchor in parse.chronology_graph.time_anchors]

    def duplicate_ids(ids: list[str], label: str) -> None:
        seen: set[str] = set()
        dupes: set[str] = set()
        for item in ids:
            if item in seen:
                dupes.add(item)
            seen.add(item)
        if dupes:
            add(
                ReviewSeverity.HIGH,
                ReviewCategory.QUALITY,
                f"Duplicate IDs in {label}",
                metadata={"duplicates": sorted(dupes)},
            )

    duplicate_ids(span_ids, "evidence_spans")
    duplicate_ids(flag_ids, "review_flags")
    duplicate_ids(actor_ids, "actor_graph.nodes")
    duplicate_ids(section_ids, "section_tree.nodes")
    duplicate_ids(packet_ids, "packet_candidates")
    duplicate_ids(message_ids, "thread_graph.message_nodes")
    duplicate_ids(time_anchor_ids, "chronology_graph.time_anchors")

    span_id_set = set(span_ids)
    flag_id_set = set(flag_ids)
    actor_id_set = set(actor_ids)
    section_id_set = set(section_ids)
    message_id_set = set(message_ids)
    time_anchor_id_set = set(time_anchor_ids)

    for span in parse.evidence_spans:
        for ref in span.review_flag_ids:
            if ref not in flag_id_set:
                add(
                    ReviewSeverity.HIGH,
                    ReviewCategory.QUALITY,
                    "Evidence span references unknown review_flag_id",
                    span_id=span.span_id,
                    metadata={"review_flag_id": ref},
                )
        if span.speaker_id and span.speaker_id not in actor_id_set:
            add(ReviewSeverity.WARNING, ReviewCategory.MISSING_EVIDENCE, "Evidence span speaker_id not found in actor graph", span_id=span.span_id, metadata={"speaker_id": span.speaker_id})
        if span.author_id and span.author_id not in actor_id_set:
            add(ReviewSeverity.WARNING, ReviewCategory.MISSING_EVIDENCE, "Evidence span author_id not found in actor graph", span_id=span.span_id, metadata={"author_id": span.author_id})
        if span.message_id and span.message_id not in message_id_set:
            add(ReviewSeverity.HIGH, ReviewCategory.QUALITY, "Evidence span references unknown message_id", span_id=span.span_id, metadata={"message_id": span.message_id})
        if span.time_anchor_id and span.time_anchor_id not in time_anchor_id_set:
            add(ReviewSeverity.WARNING, ReviewCategory.MISSING_EVIDENCE, "Evidence span references unknown time_anchor_id", span_id=span.span_id, metadata={"time_anchor_id": span.time_anchor_id})
        if span.previous_span_id and span.previous_span_id not in span_id_set:
            add(ReviewSeverity.HIGH, ReviewCategory.QUALITY, "Evidence span previous_span_id not found", span_id=span.span_id, metadata={"previous_span_id": span.previous_span_id})
        if span.next_span_id and span.next_span_id not in span_id_set:
            add(ReviewSeverity.HIGH, ReviewCategory.QUALITY, "Evidence span next_span_id not found", span_id=span.span_id, metadata={"next_span_id": span.next_span_id})

    rank_to_spans: dict[int, list[str]] = defaultdict(list)
    for span in parse.evidence_spans:
        if span.chronology_rank is not None:
            rank_to_spans[span.chronology_rank].append(span.span_id)
    for rank, refs in sorted(rank_to_spans.items()):
        if len(refs) > 1:
            add(ReviewSeverity.INFO, ReviewCategory.QUALITY, "Multiple evidence spans share the same chronology_rank", metadata={"chronology_rank": rank, "span_ids": sorted(refs)})

    for edge in parse.actor_graph.edges:
        if edge.source_actor_id not in actor_id_set or edge.target_actor_id not in actor_id_set:
            add(ReviewSeverity.HIGH, ReviewCategory.QUALITY, "ActorEdge references unknown actor node", metadata={"source_actor_id": edge.source_actor_id, "target_actor_id": edge.target_actor_id})
        for span_id in edge.evidence_span_ids:
            if span_id not in span_id_set:
                add(ReviewSeverity.HIGH, ReviewCategory.QUALITY, "ActorEdge references unknown evidence span", metadata={"span_id": span_id})

    section_map = {node.section_id: node for node in parse.section_tree.nodes}
    if parse.section_tree.root_section_id and parse.section_tree.root_section_id not in section_map:
        add(ReviewSeverity.HIGH, ReviewCategory.QUALITY, "SectionTree root_section_id is missing from nodes", metadata={"root_section_id": parse.section_tree.root_section_id})
    for node in parse.section_tree.nodes:
        if node.parent_section_id and node.parent_section_id not in section_map:
            add(ReviewSeverity.HIGH, ReviewCategory.QUALITY, "SectionNode references unknown parent_section_id", metadata={"section_id": node.section_id, "parent_section_id": node.parent_section_id})
        for child_id in node.child_section_ids:
            if child_id not in section_map:
                add(ReviewSeverity.HIGH, ReviewCategory.QUALITY, "SectionNode references unknown child_section_id", metadata={"section_id": node.section_id, "child_section_id": child_id})
            else:
                child_parent = section_map[child_id].parent_section_id
                if child_parent != node.section_id:
                    add(ReviewSeverity.WARNING, ReviewCategory.QUALITY, "Section parent/child links are not reciprocal", metadata={"section_id": node.section_id, "child_section_id": child_id, "child_parent_section_id": child_parent})
        for span_id in node.span_ids:
            if span_id not in span_id_set:
                add(ReviewSeverity.HIGH, ReviewCategory.QUALITY, "SectionNode references unknown span_id", metadata={"section_id": node.section_id, "span_id": span_id})

    if parse.thread_graph:
        for node in parse.thread_graph.message_nodes:
            if node.author_id and node.author_id not in actor_id_set:
                add(ReviewSeverity.WARNING, ReviewCategory.MISSING_EVIDENCE, "MessageNode author_id not found in actor graph", metadata={"message_id": node.message_id, "author_id": node.author_id})
            if node.speaker_id and node.speaker_id not in actor_id_set:
                add(ReviewSeverity.WARNING, ReviewCategory.MISSING_EVIDENCE, "MessageNode speaker_id not found in actor graph", metadata={"message_id": node.message_id, "speaker_id": node.speaker_id})
            if node.section_id and node.section_id not in section_id_set:
                add(ReviewSeverity.HIGH, ReviewCategory.QUALITY, "MessageNode references unknown section_id", metadata={"message_id": node.message_id, "section_id": node.section_id})
            if node.time_anchor_id and node.time_anchor_id not in time_anchor_id_set:
                add(ReviewSeverity.WARNING, ReviewCategory.MISSING_EVIDENCE, "MessageNode references unknown time_anchor_id", metadata={"message_id": node.message_id, "time_anchor_id": node.time_anchor_id})
            for span_id in node.span_ids:
                if span_id not in span_id_set:
                    add(ReviewSeverity.HIGH, ReviewCategory.QUALITY, "MessageNode references unknown span_id", metadata={"message_id": node.message_id, "span_id": span_id})
        for edge in parse.thread_graph.edges:
            if edge.source_message_id not in message_id_set or edge.target_message_id not in message_id_set:
                add(ReviewSeverity.HIGH, ReviewCategory.QUALITY, "ThreadEdge references unknown message node", metadata={"source_message_id": edge.source_message_id, "target_message_id": edge.target_message_id})

    for edge in parse.chronology_graph.edges:
        if edge.source_time_anchor_id not in time_anchor_id_set or edge.target_time_anchor_id not in time_anchor_id_set:
            add(ReviewSeverity.HIGH, ReviewCategory.QUALITY, "ChronologyEdge references unknown time anchor", metadata={"source_time_anchor_id": edge.source_time_anchor_id, "target_time_anchor_id": edge.target_time_anchor_id})

    for edge in parse.evidence_graph.edges:
        if edge.source_span_id not in span_id_set or edge.target_span_id not in span_id_set:
            add(ReviewSeverity.HIGH, ReviewCategory.QUALITY, "EvidenceEdge references unknown evidence span", metadata={"source_span_id": edge.source_span_id, "target_span_id": edge.target_span_id})

    for packet in parse.packet_candidates:
        if packet.primary_span_id and packet.primary_span_id not in span_id_set:
            add(ReviewSeverity.HIGH, ReviewCategory.QUALITY, "PacketCandidate primary_span_id not found in evidence spans", metadata={"packet_id": packet.packet_id, "primary_span_id": packet.primary_span_id})
        for span_id in packet.span_ids:
            if span_id not in span_id_set:
                add(ReviewSeverity.HIGH, ReviewCategory.QUALITY, "PacketCandidate references unknown span_id", metadata={"packet_id": packet.packet_id, "span_id": span_id})
        for flag_id in packet.review_flag_ids:
            if flag_id not in flag_id_set:
                add(ReviewSeverity.HIGH, ReviewCategory.QUALITY, "PacketCandidate references unknown review_flag_id", metadata={"packet_id": packet.packet_id, "review_flag_id": flag_id})

    return issues


class DocumentParseBuilder:
    """Builder for deterministic, validated DocumentParse instances."""

    def __init__(
        self,
        *,
        doc_id: str,
        pack_id: str,
        role_id: str,
        modality: str,
        container_type: ContainerType,
        discourse_type: DiscourseType,
        source_layer: SourceLayer = SourceLayer.NORMALIZED,
    ) -> None:
        self.doc_id = doc_id
        self.pack_id = pack_id
        self.role_id = role_id
        self.modality = modality
        self.container_type = container_type
        self.discourse_type = discourse_type
        self.source_layer = source_layer
        self._evidence_spans: dict[str, EvidenceSpan] = {}
        self._review_flags: dict[str, ReviewFlag] = {}
        self._actor_nodes: dict[str, ActorNode] = {}
        self._actor_edges: list[ActorEdge] = []
        self._section_nodes: dict[str, SectionNode] = {}
        self._section_root_id: str | None = None
        self._thread_id: str | None = None
        self._message_nodes: dict[str, MessageNode] = {}
        self._thread_edges: list[ThreadEdge] = []
        self._time_anchors: dict[str, TimeAnchor] = {}
        self._chronology_edges: list[ChronologyEdge] = []
        self._evidence_edges: list[EvidenceEdge] = []
        self._packet_candidates: dict[str, PacketCandidate] = {}
        self._metadata: dict[str, Any] = {}

    def set_metadata(self, metadata: Mapping[str, Any]) -> "DocumentParseBuilder":
        self._metadata = dict(metadata)
        return self

    def set_section_root(self, section_id: str) -> "DocumentParseBuilder":
        self._section_root_id = section_id
        return self

    def set_thread_id(self, thread_id: str) -> "DocumentParseBuilder":
        self._thread_id = thread_id
        return self

    def add_review_flag(self, flag: ReviewFlag) -> "DocumentParseBuilder":
        if flag.flag_id in self._review_flags:
            raise ParseInvariantError(f"Duplicate review flag ID: {flag.flag_id}")
        self._review_flags[flag.flag_id] = flag
        return self

    def add_evidence_span(self, span: EvidenceSpan) -> "DocumentParseBuilder":
        if span.doc_id != self.doc_id:
            raise ParseInvariantError("EvidenceSpan.doc_id must match builder doc_id")
        if span.span_id in self._evidence_spans:
            raise ParseInvariantError(f"Duplicate evidence span ID: {span.span_id}")
        self._evidence_spans[span.span_id] = span
        return self

    def add_actor_node(self, node: ActorNode) -> "DocumentParseBuilder":
        if node.actor_id in self._actor_nodes:
            raise ParseInvariantError(f"Duplicate actor ID: {node.actor_id}")
        self._actor_nodes[node.actor_id] = node
        return self

    def add_actor_edge(self, edge: ActorEdge) -> "DocumentParseBuilder":
        self._actor_edges.append(edge)
        return self

    def add_section_node(self, node: SectionNode) -> "DocumentParseBuilder":
        if node.section_id in self._section_nodes:
            raise ParseInvariantError(f"Duplicate section ID: {node.section_id}")
        self._section_nodes[node.section_id] = node
        return self

    def add_message_node(self, node: MessageNode) -> "DocumentParseBuilder":
        if node.message_id in self._message_nodes:
            raise ParseInvariantError(f"Duplicate message ID: {node.message_id}")
        self._message_nodes[node.message_id] = node
        if self._thread_id is None and node.thread_id:
            self._thread_id = node.thread_id
        return self

    def add_thread_edge(self, edge: ThreadEdge) -> "DocumentParseBuilder":
        self._thread_edges.append(edge)
        return self

    def add_time_anchor(self, anchor: TimeAnchor) -> "DocumentParseBuilder":
        if anchor.time_anchor_id in self._time_anchors:
            raise ParseInvariantError(f"Duplicate time anchor ID: {anchor.time_anchor_id}")
        self._time_anchors[anchor.time_anchor_id] = anchor
        return self

    def add_chronology_edge(self, edge: ChronologyEdge) -> "DocumentParseBuilder":
        self._chronology_edges.append(edge)
        return self

    def add_evidence_edge(self, edge: EvidenceEdge) -> "DocumentParseBuilder":
        self._evidence_edges.append(edge)
        return self

    def add_packet_candidate(self, packet: PacketCandidate) -> "DocumentParseBuilder":
        if packet.packet_id in self._packet_candidates:
            raise ParseInvariantError(f"Duplicate packet ID: {packet.packet_id}")
        self._packet_candidates[packet.packet_id] = packet
        return self

    def build(self, *, validate: bool = True, strict: bool = True) -> DocumentParse:
        actor_graph = ActorGraph(
            nodes=tuple(sorted(self._actor_nodes.values(), key=lambda node: node.actor_id)),
            edges=tuple(
                sorted(
                    self._actor_edges,
                    key=lambda edge: (edge.source_actor_id, edge.target_actor_id, edge.relation_type.value),
                )
            ),
        )
        section_tree = SectionTree(
            nodes=tuple(sorted(self._section_nodes.values(), key=lambda node: node.section_id)),
            root_section_id=self._section_root_id,
        )
        thread_graph = None
        if self._message_nodes or self._thread_edges or self._thread_id is not None:
            thread_graph = ThreadGraph(
                thread_id=self._thread_id or "thread:default",
                message_nodes=tuple(sorted(self._message_nodes.values(), key=lambda node: node.message_id)),
                edges=tuple(
                    sorted(
                        self._thread_edges,
                        key=lambda edge: (edge.source_message_id, edge.target_message_id, edge.relation_type.value),
                    )
                ),
            )
        chronology_graph = ChronologyGraph(
            time_anchors=tuple(sorted(self._time_anchors.values(), key=lambda anchor: anchor.time_anchor_id)),
            edges=tuple(
                sorted(
                    self._chronology_edges,
                    key=lambda edge: (
                        edge.source_time_anchor_id,
                        edge.target_time_anchor_id,
                        edge.relation_type.value,
                    ),
                )
            ),
        )
        evidence_graph = EvidenceGraph(
            edges=tuple(
                sorted(
                    self._evidence_edges,
                    key=lambda edge: (edge.source_span_id, edge.target_span_id, edge.relation_type.value),
                )
            )
        )
        result = DocumentParse(
            doc_id=self.doc_id,
            pack_id=self.pack_id,
            role_id=self.role_id,
            modality=self.modality,
            container_type=self.container_type,
            discourse_type=self.discourse_type,
            source_layer=self.source_layer,
            evidence_spans=tuple(sorted(self._evidence_spans.values(), key=lambda span: span.span_id)),
            review_flags=tuple(sorted(self._review_flags.values(), key=lambda flag: flag.flag_id)),
            actor_graph=actor_graph,
            section_tree=section_tree,
            thread_graph=thread_graph,
            chronology_graph=chronology_graph,
            evidence_graph=evidence_graph,
            packet_candidates=tuple(sorted(self._packet_candidates.values(), key=lambda packet: packet.packet_id)),
            metadata=self._metadata,
        )
        if validate:
            issues = validate_document_parse(result)
            if strict and any(issue.severity is ReviewSeverity.HIGH for issue in issues):
                message = "; ".join(issue.message for issue in issues if issue.severity is ReviewSeverity.HIGH)
                raise ParseInvariantError(message or "DocumentParse contains high-severity validation issues")
        return result

