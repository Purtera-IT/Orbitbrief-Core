from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

BBox = tuple[float, float, float, float]


def _mapping(value: Mapping[str, Any] | None) -> dict[str, Any]:
    return dict(value or {})


@dataclass(frozen=True, slots=True)
class SiteSchematicTableCellObservation:
    row_index: int
    col_index: int
    text: str
    confidence: float
    bbox: BBox | None = None
    source_mode: str = "model_assisted"
    provider: str = "unknown"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicTableObservation:
    table_id: str
    page_index: int
    text: str
    confidence: float
    bbox: BBox | None = None
    source_mode: str = "model_assisted"
    provider: str = "unknown"
    cells: tuple[SiteSchematicTableCellObservation, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["cells"] = [cell.to_dict() for cell in self.cells]
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicLayoutBlockObservation:
    block_id: str
    page_index: int
    text: str
    role: str
    confidence: float
    bbox: BBox | None = None
    source_mode: str = "model_assisted"
    provider: str = "unknown"
    reading_order: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicWordObservation:
    word_id: str
    page_index: int
    text: str
    bbox: BBox
    reading_order: int
    confidence: float = 0.0
    source_mode: str = "pdf_native"
    provider: str = "fitz"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicVectorObservation:
    vector_id: str
    page_index: int
    kind: str
    bbox: BBox | None
    confidence: float = 0.0
    source_mode: str = "pdf_native"
    provider: str = "fitz"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicPageModalityDecision:
    page_index: int
    sheet_type: str
    modality: str
    confidence: float
    ambiguous: bool = False
    scores: Mapping[str, float] = field(default_factory=dict)
    reasons: tuple[str, ...] = ()
    diagnostics: Mapping[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["ambiguous"] = bool(self.ambiguous)
        data["scores"] = dict(self.scores)
        data["reasons"] = list(self.reasons)
        data["diagnostics"] = dict(self.diagnostics)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicVectorPrimitiveValidation:
    primitive_id: str
    valid: bool
    quality_score: float
    candidate_kind: str
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["reasons"] = list(self.reasons)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicPacketV0V1Summary:
    packet_id: str
    page_count: int
    modality_counts: Mapping[str, int] = field(default_factory=dict)
    ambiguous_page_count: int = 0
    primitive_count: int = 0
    validated_primitive_count: int = 0
    leader_candidate_count: int = 0
    dimension_candidate_count: int = 0
    modality_fail: bool = False
    primitive_graph_fail: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["modality_counts"] = dict(self.modality_counts)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicVectorPrimitive:
    primitive_id: str
    primitive_kind: str
    bbox: BBox | None
    page_index: int
    confidence: float
    source_mode: str = "pdf_native"
    provider: str = "fitz"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicVectorJunction:
    junction_id: str
    x: float
    y: float
    primitive_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["primitive_ids"] = list(self.primitive_ids)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicVectorPrimitiveGraph:
    page_index: int
    primitive_ids: tuple[str, ...] = ()
    junctions: tuple[SiteSchematicVectorJunction, ...] = ()
    leader_candidate_ids: tuple[str, ...] = ()
    connector_candidate_ids: tuple[str, ...] = ()
    dimension_candidate_ids: tuple[str, ...] = ()
    diagnostics: Mapping[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["primitive_ids"] = list(self.primitive_ids)
        data["junctions"] = [row.to_dict() for row in self.junctions]
        data["leader_candidate_ids"] = list(self.leader_candidate_ids)
        data["connector_candidate_ids"] = list(self.connector_candidate_ids)
        data["dimension_candidate_ids"] = list(self.dimension_candidate_ids)
        data["diagnostics"] = dict(self.diagnostics)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicMeasurementCandidate:
    measurement_id: str
    page_index: int
    bbox: BBox | None
    measurement_source: str
    scale_source: str
    confidence: float
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicPageObservation:
    page_index: int
    page_text: str
    confidence: float
    source_mode: str = "model_assisted"
    provider: str = "unknown"
    words: tuple[SiteSchematicWordObservation, ...] = ()
    layout_blocks: tuple[SiteSchematicLayoutBlockObservation, ...] = ()
    reading_order: tuple[str, ...] = ()
    table_blocks: tuple[SiteSchematicTableObservation, ...] = ()
    vector_items: tuple[SiteSchematicVectorObservation, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["words"] = [word.to_dict() for word in self.words]
        data["layout_blocks"] = [block.to_dict() for block in self.layout_blocks]
        data["table_blocks"] = [table.to_dict() for table in self.table_blocks]
        data["vector_items"] = [row.to_dict() for row in self.vector_items]
        data["reading_order"] = list(self.reading_order)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicUniversalTableCell:
    cell_id: str
    table_id: str
    row_id: str
    row_index: int
    col_index: int
    bbox: BBox | None
    raw_text: str
    normalized_text: str
    rowspan: int = 1
    colspan: int = 1
    source_token_ids: tuple[str, ...] = ()
    confidence: float = 0.0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["source_token_ids"] = list(self.source_token_ids)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicUniversalTableRow:
    row_id: str
    table_id: str
    row_index: int
    bbox: BBox | None
    is_header: bool
    cells: tuple[SiteSchematicUniversalTableCell, ...] = ()
    raw_text_joined: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["cells"] = [cell.to_dict() for cell in self.cells]
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicUniversalTable:
    table_id: str
    packet_id: str
    pdf_id: str
    page_index: int
    sheet_number: str
    sheet_title: str
    region_id: str
    detail_region_id: str | None
    subregion_id: str | None
    pseudo_page_id: str | None
    table_kind: str
    bbox: BBox | None
    source_mode: str
    provider: str
    confidence: float
    row_count: int
    column_count: int
    rows: tuple[SiteSchematicUniversalTableRow, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["rows"] = [row.to_dict() for row in self.rows]
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicSemanticLineageRef:
    semantic_object_type: str
    semantic_object_id: str
    source_table_id: str
    source_row_id: str
    source_cell_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["source_cell_ids"] = list(self.source_cell_ids)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicRegion:
    region_id: str
    page_index: int
    kind: str
    text: str
    confidence: float
    bbox: BBox | None = None
    source_mode: str = "text_heuristic"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicDetailRegion:
    detail_region_id: str
    page_index: int
    parent_region_id: str
    kind: str
    text: str
    confidence: float
    bbox: BBox | None = None
    source_mode: str = "text_heuristic"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicSubregion:
    subregion_id: str
    page_index: int
    parent_region_id: str
    detail_region_id: str
    role: str
    text: str
    confidence: float
    bbox: BBox | None = None
    source_mode: str = "text_heuristic"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicPseudoPage:
    pseudo_page_id: str
    page_index: int
    parent_region_id: str
    detail_region_id: str
    subregion_id: str
    role: str
    text: str
    confidence: float
    bbox: BBox | None = None
    source_mode: str = "text_heuristic"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicScopedNoteLink:
    link_id: str
    page_index: int
    note_text: str
    scope_level: str = "page_global"
    scope_targets: tuple[str, ...] = ()
    confidence: float = 0.0
    status: str = "scoped"
    parent_region_id: str = ""
    pseudo_page_id: str = ""
    source_mode: str = "text_heuristic"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["scope_targets"] = list(self.scope_targets)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicLegendEntry:
    entry_id: str
    page_index: int
    section: str
    label: str
    description: str
    primitive_kind: str = ""
    symbol_token: str = ""
    overlay_tags: tuple[str, ...] = ()
    confidence: float = 0.0
    source_table_id: str = ""
    source_row_id: str = ""
    source_cell_ids: tuple[str, ...] = ()
    rules: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["overlay_tags"] = list(self.overlay_tags)
        data["source_cell_ids"] = list(self.source_cell_ids)
        data["rules"] = _mapping(self.rules)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicOutletTypeDefinition:
    definition_id: str
    page_index: int
    label: str
    cable_count: int | None = None
    cable_type: str = ""
    work_area_termination: str = ""
    closet_termination: str = ""
    mounting: str = ""
    power_requirement: str = ""
    remarks: str = ""
    confidence: float = 0.0
    status: str = "stated"
    source_table_id: str = ""
    source_row_id: str = ""
    source_cell_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["source_cell_ids"] = list(self.source_cell_ids)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicMountingRule:
    rule_id: str
    page_index: int
    text: str
    confidence: float
    status: str = "stated"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicTerminationRule:
    rule_id: str
    page_index: int
    text: str
    confidence: float
    status: str = "stated"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicColorConvention:
    convention_id: str
    page_index: int
    color: str
    meaning: str
    confidence: float
    status: str = "stated"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicAbbreviationEntry:
    entry_id: str
    page_index: int
    token: str
    meaning: str
    category: str = "abbreviation"
    confidence: float = 0.0
    source_table_id: str = ""
    source_row_id: str = ""
    source_cell_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["source_cell_ids"] = list(self.source_cell_ids)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicDrawingIndexRow:
    row_id: str
    page_index: int
    sheet_number: str
    sheet_title: str
    confidence: float
    status: str = "stated"
    source_table_id: str = ""
    source_row_id: str = ""
    source_cell_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["source_cell_ids"] = list(self.source_cell_ids)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicNoteClause:
    clause_id: str
    page_index: int
    text: str
    clause_type: str = "general_rule"
    confidence: float = 0.0
    status: str = "stated"
    scope_level: str = "page_global"
    scope_targets: tuple[str, ...] = ()
    parent_region_id: str = ""
    pseudo_page_id: str = ""
    bbox: BBox | None = None
    source_mode: str = "text_heuristic"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["scope_targets"] = list(self.scope_targets)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicEnvironmentalRequirement:
    requirement_id: str
    page_index: int
    text: str
    confidence: float
    status: str = "stated"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicGroundingRequirement:
    requirement_id: str
    page_index: int
    text: str
    confidence: float
    status: str = "stated"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicTestingRequirement:
    requirement_id: str
    page_index: int
    text: str
    confidence: float
    status: str = "stated"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicLabelingRequirement:
    requirement_id: str
    page_index: int
    text: str
    confidence: float
    status: str = "stated"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicResponsibilityAssignment:
    assignment_id: str
    page_index: int
    assignee: str
    text: str
    confidence: float
    status: str = "coordination_required"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicCableRule:
    rule_id: str
    page_index: int
    text: str
    confidence: float
    status: str = "stated"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicPathwayRule:
    rule_id: str
    page_index: int
    text: str
    confidence: float
    status: str = "stated"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicServiceLoopRequirement:
    requirement_id: str
    page_index: int
    text: str
    confidence: float
    status: str = "stated"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicSymbolInstance:
    instance_id: str
    page_index: int
    token: str
    primitive_kind: str
    text: str
    confidence: float
    overlay_tags: tuple[str, ...] = ()
    region_id: str = ""
    bbox: BBox | None = None
    source_mode: str = "ocr_token_heuristic"
    line_index: int | None = None
    room_label: str = ""
    parent_region_id: str = ""
    pseudo_page_id: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["overlay_tags"] = list(self.overlay_tags)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicPrimitiveDetection:
    detection_id: str
    page_index: int
    primitive_family: str
    token_hint: str = ""
    bbox: BBox | None = None
    score: float = 0.0
    source_provider: str = "detector_placeholder"
    region_id: str = ""
    detail_region_id: str = ""
    subregion_id: str = ""
    pseudo_page_id: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicDeviceInstance:
    device_id: str
    page_index: int
    token: str
    device_type: str
    text: str
    room_label: str = ""
    confidence: float = 0.0
    status: str = "inferred"
    parent_region_id: str = ""
    pseudo_page_id: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicOutletInstance:
    outlet_id: str
    page_index: int
    outlet_type: str
    text: str
    room_label: str = ""
    confidence: float = 0.0
    status: str = "inferred"
    parent_region_id: str = ""
    pseudo_page_id: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicRoom:
    room_id: str
    page_index: int
    label: str
    room_kind: str = "room"
    confidence: float = 0.0
    status: str = "stated"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicCloset:
    closet_id: str
    page_index: int
    label: str
    closet_kind: str = "idf"
    confidence: float = 0.0
    status: str = "stated"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicRack:
    rack_id: str
    page_index: int
    label: str
    confidence: float = 0.0
    status: str = "stated"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicRiserEdge:
    edge_id: str
    page_index: int
    source_label: str
    target_label: str
    medium: str
    confidence: float
    status: str = "inferred"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicTopologySegment:
    segment_id: str
    page_index: int
    text: str
    confidence: float
    status: str = "stated"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicTopologyEndpoint:
    endpoint_id: str
    page_index: int
    profile_id: str
    endpoint_kind: str
    detector_class_id: str
    symbol_instance_ids: tuple[str, ...] = ()
    region_id: str = ""
    detail_region_id: str = ""
    subregion_id: str = ""
    pseudo_page_id: str = ""
    confidence: float = 0.0
    status: str = "candidate"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["symbol_instance_ids"] = list(self.symbol_instance_ids)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicTopologyRelation:
    relation_id: str
    page_index: int
    profile_id: str
    relation_kind: str
    source_endpoint_id: str
    target_endpoint_id: str
    supporting_symbol_link_ids: tuple[str, ...] = ()
    confidence: float = 0.0
    status: str = "candidate"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["supporting_symbol_link_ids"] = list(self.supporting_symbol_link_ids)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicReasoningFinding:
    finding_id: str
    finding_type: str
    severity: str
    status: str
    confidence: float
    summary: str
    triage_bucket: str = "low_priority_review"
    priority_score: float = 0.0
    evidence_node_ids: tuple[str, ...] = ()
    evidence_edge_ids: tuple[str, ...] = ()
    evidence_symbol_instance_ids: tuple[str, ...] = ()
    evidence_topology_ids: tuple[str, ...] = ()
    page_indices: tuple[int, ...] = ()
    profile_ids: tuple[str, ...] = ()
    suggested_action: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["evidence_node_ids"] = list(self.evidence_node_ids)
        data["evidence_edge_ids"] = list(self.evidence_edge_ids)
        data["evidence_symbol_instance_ids"] = list(self.evidence_symbol_instance_ids)
        data["evidence_topology_ids"] = list(self.evidence_topology_ids)
        data["page_indices"] = list(self.page_indices)
        data["profile_ids"] = list(self.profile_ids)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicConsistencyCheck:
    check_id: str
    check_type: str
    status: str
    confidence: float
    summary: str
    evidence_finding_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["evidence_finding_ids"] = list(self.evidence_finding_ids)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicContradictionFlag:
    flag_id: str
    status: str
    confidence: float
    summary: str
    related_finding_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["related_finding_ids"] = list(self.related_finding_ids)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicAnchorReconciliationSuggestion:
    suggestion_id: str
    status: str
    confidence: float
    summary: str
    symbol_instance_id: str = ""
    legend_entry_id: str = ""
    topology_endpoint_ids: tuple[str, ...] = ()
    related_finding_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["topology_endpoint_ids"] = list(self.topology_endpoint_ids)
        data["related_finding_ids"] = list(self.related_finding_ids)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicTopologyReviewSuggestion:
    suggestion_id: str
    status: str
    confidence: float
    summary: str
    profile_id: str = ""
    topology_relation_id: str = ""
    topology_endpoint_ids: tuple[str, ...] = ()
    related_finding_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["topology_endpoint_ids"] = list(self.topology_endpoint_ids)
        data["related_finding_ids"] = list(self.related_finding_ids)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicPacketReasoningSummary:
    summary_id: str
    packet_scope: str
    total_findings: int
    supported_count: int
    needs_review_count: int
    contradicted_count: int
    high_priority_count: int
    summary: str
    top_review_profiles: tuple[str, ...] = ()
    top_review_families: tuple[str, ...] = ()
    supporting_finding_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["top_review_profiles"] = list(self.top_review_profiles)
        data["top_review_families"] = list(self.top_review_families)
        data["supporting_finding_ids"] = list(self.supporting_finding_ids)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicFamilyConsistencySummary:
    family: str
    total_findings: int
    supported_count: int
    mixed_count: int
    high_priority_count: int
    topology_supported_count: int
    status: str
    page_indices: tuple[int, ...] = ()
    profile_ids: tuple[str, ...] = ()
    supporting_finding_ids: tuple[str, ...] = ()
    supporting_node_ids: tuple[str, ...] = ()
    supporting_edge_ids: tuple[str, ...] = ()
    supporting_symbol_ids: tuple[str, ...] = ()
    supporting_topology_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["page_indices"] = list(self.page_indices)
        data["profile_ids"] = list(self.profile_ids)
        data["supporting_finding_ids"] = list(self.supporting_finding_ids)
        data["supporting_node_ids"] = list(self.supporting_node_ids)
        data["supporting_edge_ids"] = list(self.supporting_edge_ids)
        data["supporting_symbol_ids"] = list(self.supporting_symbol_ids)
        data["supporting_topology_ids"] = list(self.supporting_topology_ids)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicReviewQueueSummary:
    queue_id: str
    total_items: int
    high_priority_items: int
    medium_priority_items: int
    low_priority_items: int
    queue_buckets: Mapping[str, int]
    top_families: tuple[str, ...] = ()
    top_profiles: tuple[str, ...] = ()
    page_indices: tuple[int, ...] = ()
    supporting_finding_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["queue_buckets"] = dict(self.queue_buckets)
        data["top_families"] = list(self.top_families)
        data["top_profiles"] = list(self.top_profiles)
        data["page_indices"] = list(self.page_indices)
        data["supporting_finding_ids"] = list(self.supporting_finding_ids)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicTopologyCoverageSummary:
    summary_id: str
    endpoint_count: int
    relation_count: int
    inferred_endpoint_count: int
    unresolved_endpoint_count: int
    inferred_relation_count: int
    unresolved_relation_count: int
    endpoint_profile_counts: Mapping[str, int]
    relation_profile_counts: Mapping[str, int]
    top_family_endpoint_counts: Mapping[str, int]
    top_family_relation_counts: Mapping[str, int]
    sparse_profiles: tuple[str, ...] = ()
    supporting_topology_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["endpoint_profile_counts"] = dict(self.endpoint_profile_counts)
        data["relation_profile_counts"] = dict(self.relation_profile_counts)
        data["top_family_endpoint_counts"] = dict(self.top_family_endpoint_counts)
        data["top_family_relation_counts"] = dict(self.top_family_relation_counts)
        data["sparse_profiles"] = list(self.sparse_profiles)
        data["supporting_topology_ids"] = list(self.supporting_topology_ids)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicProfileQASummary:
    profile_id: str
    total_findings: int
    supported_count: int
    review_count: int
    contradiction_count: int
    high_priority_count: int
    strong_anchor_count: int
    mixed_anchor_count: int
    inferred_topology_count: int
    unresolved_topology_count: int
    top_families: tuple[str, ...] = ()
    page_indices: tuple[int, ...] = ()
    supporting_finding_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["top_families"] = list(self.top_families)
        data["page_indices"] = list(self.page_indices)
        data["supporting_finding_ids"] = list(self.supporting_finding_ids)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicSymbolLink:
    link_id: str
    page_index: int
    instance_id: str
    symbol_token: str
    status: str
    confidence: float
    legend_entry_id: str = ""
    legend_label: str = ""
    room_label: str = ""
    related_note_clauses: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["related_note_clauses"] = list(self.related_note_clauses)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicSymbolResolutionOutcome:
    outcome_id: str
    page_index: int
    status: str
    confidence: float
    symbol_token: str = ""
    instance_id: str = ""
    legend_entry_id: str = ""
    reason_codes: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["reason_codes"] = list(self.reason_codes)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicSymbolCandidateInput:
    candidate_id: str
    artifact_id: str
    page_index: int
    sheet_type: str
    sheet_number: str = ""
    sheet_title: str = ""
    region_id: str = ""
    detail_region_id: str = ""
    subregion_id: str = ""
    pseudo_page_id: str = ""
    bbox: BBox | None = None
    source_mode: str = "decomposition_heuristic"
    provider: str = "deterministic"
    decomposition_confidence: float = 0.0
    local_text_context: str = ""
    nearby_note_clauses: tuple[str, ...] = ()
    nearby_legend_entry_ids: tuple[str, ...] = ()
    nearby_legend_texts: tuple[str, ...] = ()
    nearby_abbreviations: tuple[str, ...] = ()
    nearby_room_labels: tuple[str, ...] = ()
    nearby_closet_labels: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["nearby_note_clauses"] = list(self.nearby_note_clauses)
        data["nearby_legend_entry_ids"] = list(self.nearby_legend_entry_ids)
        data["nearby_legend_texts"] = list(self.nearby_legend_texts)
        data["nearby_abbreviations"] = list(self.nearby_abbreviations)
        data["nearby_room_labels"] = list(self.nearby_room_labels)
        data["nearby_closet_labels"] = list(self.nearby_closet_labels)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicSymbolCandidateGroup:
    candidate_id: str
    page_index: int
    bbox: BBox | None
    primitive_ids: tuple[str, ...] = ()
    text_hints: tuple[str, ...] = ()
    family_candidates: tuple[str, ...] = ()
    confidence: float = 0.0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["primitive_ids"] = list(self.primitive_ids)
        data["text_hints"] = list(self.text_hints)
        data["family_candidates"] = list(self.family_candidates)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicLegendGroundingEntry:
    legend_id: str
    page_index: int
    family: str
    raw_label: str
    aliases: tuple[str, ...] = ()
    source_row_id: str = ""
    source_cell_ids: tuple[str, ...] = ()
    bbox: BBox | None = None
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["aliases"] = list(self.aliases)
        data["source_cell_ids"] = list(self.source_cell_ids)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicGroundedSymbol:
    grounded_id: str
    page_index: int
    candidate_id: str
    family: str
    semantic_meaning: str
    bbox: BBox | None
    legend_ids: tuple[str, ...] = ()
    supporting_text_hints: tuple[str, ...] = ()
    confidence: float = 0.0
    status: str = "grounded"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["legend_ids"] = list(self.legend_ids)
        data["supporting_text_hints"] = list(self.supporting_text_hints)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicPacketV2Summary:
    packet_id: str
    page_count: int
    candidate_symbol_count: int = 0
    grounded_symbol_count: int = 0
    ambiguous_symbol_count: int = 0
    unresolved_symbol_count: int = 0
    legend_dictionary_entry_count: int = 0
    family_counts: Mapping[str, int] = field(default_factory=dict)
    packet_level_fail: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["family_counts"] = dict(self.family_counts)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicGroundingStateDecision:
    state: str
    confidence: float
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["reasons"] = list(self.reasons)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicPacketV2HardpageSummary:
    packet_id: str
    required_page_types: tuple[str, ...] = ()
    satisfied_page_types: tuple[str, ...] = ()
    hardpage_rate: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["required_page_types"] = list(self.required_page_types)
        data["satisfied_page_types"] = list(self.satisfied_page_types)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicPacketV2QualitySummary:
    packet_id: str
    grounded_symbol_yield_rate: float = 0.0
    hardpage_grounded_symbol_yield_rate: float = 0.0
    unresolved_symbol_ratio: float = 0.0
    room_device_association_rate: float = 0.0
    connector_grounding_quality_rate: float = 0.0
    expected_family_grounded_coverage_rate: float = 0.0
    hardpage_requirement_complete: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SiteSchematicPacketV2TruthAuditSummary:
    packet_id: str
    truth_audit_reasons: tuple[str, ...] = ()
    suspicious_uniform_grounding: bool = False
    impossible_connector_success: bool = False
    impossible_room_assoc_success: bool = False
    empty_required_hardpage_set: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["truth_audit_reasons"] = list(self.truth_audit_reasons)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicPacketV2EnforcementSummary:
    packet_id: str
    expected_family_grounded_coverage_rate: float = 0.0
    hardpage_family_grounded_coverage_rate: float = 0.0
    room_device_evidence_truth_rate: float = 0.0
    connector_evidence_truth_rate: float = 0.0
    hardpage_requirement_truth_rate: float = 0.0
    hardpage_grounded_symbol_yield_rate: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SiteSchematicPacketV2FamilyCoverageSummary:
    packet_id: str
    packet_expected_families: tuple[str, ...] = tuple()
    grounded_families: tuple[str, ...] = tuple()
    hardpage_expected_families: tuple[str, ...] = tuple()
    hardpage_grounded_families: tuple[str, ...] = tuple()
    expected_family_grounded_coverage_rate: float = 0.0
    hardpage_family_grounded_coverage_rate: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SiteSchematicGraphNode:
    node_id: str
    kind: str
    label: str
    page_index: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicGraphEdge:
    edge_id: str
    source_node_id: str
    target_node_id: str
    relation: str
    confidence: float
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicGraph:
    nodes: tuple[SiteSchematicGraphNode, ...] = ()
    edges: tuple[SiteSchematicGraphEdge, ...] = ()

    def summary(self) -> dict[str, int]:
        return {
            "graph_nodes": len(self.nodes),
            "graph_edges": len(self.edges),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary(),
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
        }


@dataclass(frozen=True, slots=True)
class SiteSchematicObservation:
    observation_id: str
    page_index: int
    sheet_type: str
    zone: str
    overlay_tags: tuple[str, ...]
    kind: str
    text: str
    confidence: float
    region_id: str = ""
    bbox: BBox | None = None
    source_mode: str = "text_heuristic"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["overlay_tags"] = list(self.overlay_tags)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicPageSection:
    section_id: str
    page_index: int
    order_index: int
    section_title: str
    bbox: tuple[float, float, float, float] | None = None
    ordered_lines: tuple[str, ...] = ()
    confidence: float = 0.0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["ordered_lines"] = list(self.ordered_lines)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicPage:
    page_index: int
    page_label: str
    sheet_type: str
    overlay_tags: tuple[str, ...]
    zones: tuple[str, ...]
    legend_entries: tuple[str, ...]
    note_clauses: tuple[str, ...]
    room_labels: tuple[str, ...]
    equipment_labels: tuple[str, ...]
    sheet_number: str = ""
    sheet_title: str = ""
    region_ids: tuple[str, ...] = ()
    detail_region_ids: tuple[str, ...] = ()
    subregion_ids: tuple[str, ...] = ()
    pseudo_page_ids: tuple[str, ...] = ()
    symbol_instance_ids: tuple[str, ...] = ()
    symbol_link_ids: tuple[str, ...] = ()
    drawing_index_rows: tuple[str, ...] = ()
    review_required: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["overlay_tags"] = list(self.overlay_tags)
        data["zones"] = list(self.zones)
        data["metadata"] = _mapping(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class SiteSchematicBundle:
    source_modality: str
    page_count: int
    typed_pages: int
    overlay_counts: Mapping[str, int]
    sheet_type_counts: Mapping[str, int]
    observation_counts: Mapping[str, int]
    pages: tuple[SiteSchematicPage, ...]
    observations: tuple[SiteSchematicObservation, ...]
    page_observations: tuple[SiteSchematicPageObservation, ...] = ()
    page_modality_decisions: tuple[SiteSchematicPageModalityDecision, ...] = ()
    page_sections: tuple[SiteSchematicPageSection, ...] = ()
    vector_primitives: tuple[SiteSchematicVectorPrimitive, ...] = ()
    vector_primitive_validations: tuple[SiteSchematicVectorPrimitiveValidation, ...] = ()
    vector_primitive_graphs: tuple[SiteSchematicVectorPrimitiveGraph, ...] = ()
    measurement_candidates: tuple[SiteSchematicMeasurementCandidate, ...] = ()
    packet_v0_v1_summary: SiteSchematicPacketV0V1Summary | None = None
    symbol_candidate_groups: tuple[SiteSchematicSymbolCandidateGroup, ...] = ()
    legend_grounding_entries: tuple[SiteSchematicLegendGroundingEntry, ...] = ()
    grounded_symbols: tuple[SiteSchematicGroundedSymbol, ...] = ()
    packet_v2_summary: SiteSchematicPacketV2Summary | None = None
    packet_v2_hardpage_summary: SiteSchematicPacketV2HardpageSummary | None = None
    packet_v2_quality_summary: SiteSchematicPacketV2QualitySummary | None = None
    packet_v2_truth_audit_summary: SiteSchematicPacketV2TruthAuditSummary | None = None
    packet_v2_enforcement_summary: SiteSchematicPacketV2EnforcementSummary | None = None
    packet_v2_family_coverage_summary: SiteSchematicPacketV2FamilyCoverageSummary | None = None
    universal_tables: tuple[SiteSchematicUniversalTable, ...] = ()
    regions: tuple[SiteSchematicRegion, ...] = ()
    detail_regions: tuple[SiteSchematicDetailRegion, ...] = ()
    subregions: tuple[SiteSchematicSubregion, ...] = ()
    pseudo_pages: tuple[SiteSchematicPseudoPage, ...] = ()
    scoped_note_links: tuple[SiteSchematicScopedNoteLink, ...] = ()
    legend_entries: tuple[SiteSchematicLegendEntry, ...] = ()
    outlet_type_definitions: tuple[SiteSchematicOutletTypeDefinition, ...] = ()
    abbreviations: tuple[SiteSchematicAbbreviationEntry, ...] = ()
    drawing_index_rows: tuple[SiteSchematicDrawingIndexRow, ...] = ()
    semantic_lineage_refs: tuple[SiteSchematicSemanticLineageRef, ...] = ()
    note_clauses_structured: tuple[SiteSchematicNoteClause, ...] = ()
    mounting_rules: tuple[SiteSchematicMountingRule, ...] = ()
    termination_rules: tuple[SiteSchematicTerminationRule, ...] = ()
    color_conventions: tuple[SiteSchematicColorConvention, ...] = ()
    environmental_requirements: tuple[SiteSchematicEnvironmentalRequirement, ...] = ()
    grounding_requirements: tuple[SiteSchematicGroundingRequirement, ...] = ()
    testing_requirements: tuple[SiteSchematicTestingRequirement, ...] = ()
    labeling_requirements: tuple[SiteSchematicLabelingRequirement, ...] = ()
    responsibility_assignments: tuple[SiteSchematicResponsibilityAssignment, ...] = ()
    cable_rules: tuple[SiteSchematicCableRule, ...] = ()
    pathway_rules: tuple[SiteSchematicPathwayRule, ...] = ()
    service_loop_requirements: tuple[SiteSchematicServiceLoopRequirement, ...] = ()
    device_instances: tuple[SiteSchematicDeviceInstance, ...] = ()
    outlet_instances: tuple[SiteSchematicOutletInstance, ...] = ()
    rooms: tuple[SiteSchematicRoom, ...] = ()
    closets: tuple[SiteSchematicCloset, ...] = ()
    racks: tuple[SiteSchematicRack, ...] = ()
    riser_edges: tuple[SiteSchematicRiserEdge, ...] = ()
    topology_segments: tuple[SiteSchematicTopologySegment, ...] = ()
    topology_endpoints: tuple[SiteSchematicTopologyEndpoint, ...] = ()
    topology_relations: tuple[SiteSchematicTopologyRelation, ...] = ()
    symbol_instances: tuple[SiteSchematicSymbolInstance, ...] = ()
    symbol_links: tuple[SiteSchematicSymbolLink, ...] = ()
    symbol_resolution_outcomes: tuple[SiteSchematicSymbolResolutionOutcome, ...] = ()
    symbol_candidate_inputs: tuple[SiteSchematicSymbolCandidateInput, ...] = ()
    reasoning_findings: tuple[SiteSchematicReasoningFinding, ...] = ()
    consistency_checks: tuple[SiteSchematicConsistencyCheck, ...] = ()
    contradiction_flags: tuple[SiteSchematicContradictionFlag, ...] = ()
    anchor_reconciliation_suggestions: tuple[SiteSchematicAnchorReconciliationSuggestion, ...] = ()
    topology_review_suggestions: tuple[SiteSchematicTopologyReviewSuggestion, ...] = ()
    packet_reasoning_summary: SiteSchematicPacketReasoningSummary | None = None
    family_consistency_summaries: tuple[SiteSchematicFamilyConsistencySummary, ...] = ()
    review_queue_summary: SiteSchematicReviewQueueSummary | None = None
    topology_coverage_summary: SiteSchematicTopologyCoverageSummary | None = None
    profile_qa_summaries: tuple[SiteSchematicProfileQASummary, ...] = ()
    graph: SiteSchematicGraph = field(default_factory=SiteSchematicGraph)
    model_registry: Mapping[str, Any] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        observation_counts = dict(self.observation_counts)
        section_detector = self.model_registry.get("section_detector", {}) if isinstance(self.model_registry, Mapping) else {}
        section_detector_mode = (
            str(section_detector.get("mode", "")).strip()
            if isinstance(section_detector, Mapping)
            else ""
        )
        linked = sum(1 for link in self.symbol_links if link.status == "linked")
        weak = sum(1 for link in self.symbol_links if link.status == "weakly_linked")
        unresolved = sum(1 for link in self.symbol_links if link.status == "unresolved")
        conflicting = sum(1 for row in self.symbol_resolution_outcomes if row.status == "conflicting")
        detected_but_unmapped = sum(1 for row in self.symbol_resolution_outcomes if row.status == "detected_but_unmapped")
        candidate_requires_review = sum(1 for row in self.symbol_resolution_outcomes if row.status == "candidate_requires_review")
        legend_defined_but_unused = sum(1 for row in self.symbol_resolution_outcomes if row.status == "legend_defined_but_unused")
        return {
            "source_modality": self.source_modality,
            "page_count": self.page_count,
            "typed_pages": self.typed_pages,
            "overlay_counts": dict(self.overlay_counts),
            "sheet_type_counts": dict(self.sheet_type_counts),
            "observation_counts": observation_counts,
            "legend_entries": len(self.legend_entries) or int(observation_counts.get("legend_entry", 0)),
            "outlet_type_definitions": len(self.outlet_type_definitions),
            "drawing_index_rows": len(self.drawing_index_rows),
            "note_clauses": int(observation_counts.get("note_clause", 0)),
            "room_labels": int(observation_counts.get("room_label", 0)),
            "equipment_labels": int(observation_counts.get("equipment_label", 0)),
            "regions": len(self.regions),
            "page_observations": len(self.page_observations),
            "page_modality_decisions": len(self.page_modality_decisions),
            "page_sections": len(self.page_sections),
            "section_detector_mode": section_detector_mode,
            "vector_primitives": len(self.vector_primitives),
            "vector_primitive_validations": len(self.vector_primitive_validations),
            "vector_primitive_graphs": len(self.vector_primitive_graphs),
            "measurement_candidates": len(self.measurement_candidates),
            "has_packet_v0_v1_summary": bool(self.packet_v0_v1_summary),
            "symbol_candidate_groups": len(self.symbol_candidate_groups),
            "legend_grounding_entries": len(self.legend_grounding_entries),
            "grounded_symbols": len(self.grounded_symbols),
            "has_packet_v2_summary": bool(self.packet_v2_summary),
            "has_packet_v2_hardpage_summary": bool(self.packet_v2_hardpage_summary),
            "has_packet_v2_quality_summary": bool(self.packet_v2_quality_summary),
            "has_packet_v2_truth_audit_summary": bool(self.packet_v2_truth_audit_summary),
            "has_packet_v2_enforcement_summary": bool(self.packet_v2_enforcement_summary),
            "has_packet_v2_family_coverage_summary": bool(self.packet_v2_family_coverage_summary),
            "universal_tables": len(self.universal_tables),
            "detail_regions": len(self.detail_regions),
            "subregions": len(self.subregions),
            "pseudo_pages": len(self.pseudo_pages),
            "scoped_note_links": len(self.scoped_note_links),
            "abbreviations": len(self.abbreviations),
            "semantic_lineage_refs": len(self.semantic_lineage_refs),
            "symbol_instances": len(self.symbol_instances),
            "symbol_links": len(self.symbol_links),
            "symbol_candidate_inputs": len(self.symbol_candidate_inputs),
            "symbol_resolution_outcomes": len(self.symbol_resolution_outcomes),
            "environmental_requirements": len(self.environmental_requirements),
            "grounding_requirements": len(self.grounding_requirements),
            "testing_requirements": len(self.testing_requirements),
            "labeling_requirements": len(self.labeling_requirements),
            "responsibility_assignments": len(self.responsibility_assignments),
            "cable_rules": len(self.cable_rules),
            "pathway_rules": len(self.pathway_rules),
            "service_loop_requirements": len(self.service_loop_requirements),
            "mounting_rules": len(self.mounting_rules),
            "termination_rules": len(self.termination_rules),
            "color_conventions": len(self.color_conventions),
            "topology_endpoints": len(self.topology_endpoints),
            "topology_relations": len(self.topology_relations),
            "reasoning_findings": len(self.reasoning_findings),
            "consistency_checks": len(self.consistency_checks),
            "contradiction_flags": len(self.contradiction_flags),
            "anchor_reconciliation_suggestions": len(self.anchor_reconciliation_suggestions),
            "topology_review_suggestions": len(self.topology_review_suggestions),
            "family_consistency_summaries": len(self.family_consistency_summaries),
            "profile_qa_summaries": len(self.profile_qa_summaries),
            "has_packet_reasoning_summary": bool(self.packet_reasoning_summary),
            "has_review_queue_summary": bool(self.review_queue_summary),
            "has_topology_coverage_summary": bool(self.topology_coverage_summary),
            "linked_symbol_instances": linked,
            "weak_symbol_instances": weak,
            "unresolved_symbol_instances": unresolved,
            "conflicting_symbol_instances": conflicting,
            "detected_but_unmapped_symbol_instances": detected_but_unmapped,
            "candidate_requires_review_symbol_instances": candidate_requires_review,
            "legend_defined_but_unused": legend_defined_but_unused,
            **self.graph.summary(),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_modality": self.source_modality,
            "page_count": self.page_count,
            "typed_pages": self.typed_pages,
            "overlay_counts": dict(self.overlay_counts),
            "sheet_type_counts": dict(self.sheet_type_counts),
            "observation_counts": dict(self.observation_counts),
            "summary": self.summary(),
            "model_registry": _mapping(self.model_registry),
            "pages": [page.to_dict() for page in self.pages],
            "page_observations": [row.to_dict() for row in self.page_observations],
            "page_modality_decisions": [row.to_dict() for row in self.page_modality_decisions],
            "page_sections": [row.to_dict() for row in self.page_sections],
            "vector_primitives": [row.to_dict() for row in self.vector_primitives],
            "vector_primitive_validations": [row.to_dict() for row in self.vector_primitive_validations],
            "vector_primitive_graphs": [row.to_dict() for row in self.vector_primitive_graphs],
            "measurement_candidates": [row.to_dict() for row in self.measurement_candidates],
            "packet_v0_v1_summary": self.packet_v0_v1_summary.to_dict() if self.packet_v0_v1_summary else None,
            "symbol_candidate_groups": [row.to_dict() for row in self.symbol_candidate_groups],
            "legend_grounding_entries": [row.to_dict() for row in self.legend_grounding_entries],
            "grounded_symbols": [row.to_dict() for row in self.grounded_symbols],
            "packet_v2_summary": self.packet_v2_summary.to_dict() if self.packet_v2_summary else None,
            "packet_v2_hardpage_summary": self.packet_v2_hardpage_summary.to_dict() if self.packet_v2_hardpage_summary else None,
            "packet_v2_quality_summary": self.packet_v2_quality_summary.to_dict() if self.packet_v2_quality_summary else None,
            "packet_v2_truth_audit_summary": self.packet_v2_truth_audit_summary.to_dict() if self.packet_v2_truth_audit_summary else None,
            "packet_v2_enforcement_summary": self.packet_v2_enforcement_summary.to_dict() if self.packet_v2_enforcement_summary else None,
            "packet_v2_family_coverage_summary": self.packet_v2_family_coverage_summary.to_dict() if self.packet_v2_family_coverage_summary else None,
            "universal_tables": [row.to_dict() for row in self.universal_tables],
            "regions": [region.to_dict() for region in self.regions],
            "detail_regions": [region.to_dict() for region in self.detail_regions],
            "subregions": [region.to_dict() for region in self.subregions],
            "pseudo_pages": [row.to_dict() for row in self.pseudo_pages],
            "scoped_note_links": [row.to_dict() for row in self.scoped_note_links],
            "legend_entries": [entry.to_dict() for entry in self.legend_entries],
            "outlet_type_definitions": [entry.to_dict() for entry in self.outlet_type_definitions],
            "abbreviations": [entry.to_dict() for entry in self.abbreviations],
            "drawing_index_rows": [row.to_dict() for row in self.drawing_index_rows],
            "semantic_lineage_refs": [row.to_dict() for row in self.semantic_lineage_refs],
            "note_clauses_structured": [row.to_dict() for row in self.note_clauses_structured],
            "mounting_rules": [row.to_dict() for row in self.mounting_rules],
            "termination_rules": [row.to_dict() for row in self.termination_rules],
            "color_conventions": [row.to_dict() for row in self.color_conventions],
            "environmental_requirements": [row.to_dict() for row in self.environmental_requirements],
            "grounding_requirements": [row.to_dict() for row in self.grounding_requirements],
            "testing_requirements": [row.to_dict() for row in self.testing_requirements],
            "labeling_requirements": [row.to_dict() for row in self.labeling_requirements],
            "responsibility_assignments": [row.to_dict() for row in self.responsibility_assignments],
            "cable_rules": [row.to_dict() for row in self.cable_rules],
            "pathway_rules": [row.to_dict() for row in self.pathway_rules],
            "service_loop_requirements": [row.to_dict() for row in self.service_loop_requirements],
            "device_instances": [row.to_dict() for row in self.device_instances],
            "outlet_instances": [row.to_dict() for row in self.outlet_instances],
            "rooms": [row.to_dict() for row in self.rooms],
            "closets": [row.to_dict() for row in self.closets],
            "racks": [row.to_dict() for row in self.racks],
            "riser_edges": [row.to_dict() for row in self.riser_edges],
            "topology_segments": [row.to_dict() for row in self.topology_segments],
            "topology_endpoints": [row.to_dict() for row in self.topology_endpoints],
            "topology_relations": [row.to_dict() for row in self.topology_relations],
            "symbol_instances": [inst.to_dict() for inst in self.symbol_instances],
            "symbol_links": [link.to_dict() for link in self.symbol_links],
            "symbol_resolution_outcomes": [row.to_dict() for row in self.symbol_resolution_outcomes],
            "symbol_candidate_inputs": [row.to_dict() for row in self.symbol_candidate_inputs],
            "reasoning_findings": [row.to_dict() for row in self.reasoning_findings],
            "consistency_checks": [row.to_dict() for row in self.consistency_checks],
            "contradiction_flags": [row.to_dict() for row in self.contradiction_flags],
            "anchor_reconciliation_suggestions": [row.to_dict() for row in self.anchor_reconciliation_suggestions],
            "topology_review_suggestions": [row.to_dict() for row in self.topology_review_suggestions],
            "packet_reasoning_summary": self.packet_reasoning_summary.to_dict() if self.packet_reasoning_summary else None,
            "family_consistency_summaries": [row.to_dict() for row in self.family_consistency_summaries],
            "review_queue_summary": self.review_queue_summary.to_dict() if self.review_queue_summary else None,
            "topology_coverage_summary": self.topology_coverage_summary.to_dict() if self.topology_coverage_summary else None,
            "profile_qa_summaries": [row.to_dict() for row in self.profile_qa_summaries],
            "graph": self.graph.to_dict(),
            "observations": [obs.to_dict() for obs in self.observations],
        }
