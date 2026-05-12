# Site Schematic, Shared Contracts, and OrbitBrief Boundary

This document explains how parser outputs map (or do not yet map) to shared contracts, and what boundary OrbitBrief should consume.

## 1) Current Contract Surfaces in Runtime Spine

Core runtime contract models:

- `src/orbitbrief_core/runtime_spine/contracts.py`
  - `FieldClaim`
  - `ReviewFlag`
  - `PlannerInput`
  - `PlannerOutput`
  - related graph/diagnostic contract objects

Claim ontology for extractor internals:

- `src/orbitbrief_core/runtime_spine/extractors/narrative_claim_ontology.py`
  - `InternalClaim`
  - `EvidenceRef`
  - `EvidenceRefSet`
  - `ExtractionDiagnostic`

Policy substrate:

- `src/orbitbrief_core/runtime_spine/compiled_pack_runtime.py`

These are currently the hard runtime boundary that downstream packaging and planning consume.

## 2) Where Site Schematic Output Lives Today

Primary site-schematic structured output:

- `SiteSchematicBundle` from `src/orbitbrief_core/parser/site_schematic/models.py`

How it is attached:

- `SiteSchematicPdfAdapter.parse()` / `SiteSchematicImageAdapter.parse()` write:
  - `metadata["site_schematic_bundle"]`
  - `metadata["site_schematic_summary"]`
  - `metadata["site_schematic_alias"]`

Implication:

- Site-schematic structured data exists, but is attached as metadata enrichment on `DocumentParse`, not yet the sole runtime contract consumed downstream.

## 3) Current Downstream Path OrbitBrief Core Uses

Effective flow today:

1. packets -> `InternalClaim[]` via narrative extractors,
2. projection -> `FieldClaim[]`,
3. postprocess legality/normalization/contradictions,
4. package join -> canonical package-level claims.

Files:

- `runtime_spine/extractors/narrative_extractor.py`
- `runtime_spine/extractors/narrative_projector.py`
- `runtime_spine/postprocess/*`
- `runtime_spine/package_pipeline.py`
- `runtime_spine/package_joiner.py`

Current reality:

- OrbitBrief-facing outputs are still claim-centric contracts.
- Site-schematic graph/bundle is not yet the primary downstream contract boundary.

## 4) Shared Contracts Repository Alignment (Current)

Observed schema anchor examples:

- `Shared-contracts/contracts/orbitbrief/professional_services/transcript_or_notes/base/source/managed_services_base_source_contracts.json`

Current fit:

- Existing shared schemas heavily reflect traditional narrative modalities (`txt`, `docx`, `md`, `pdf_text`, `pdf_ocr`, etc.).
- Site-schematic graph-native object families are not yet expressed as first-class contract objects in the same way.

Risk:

- If claim projection omits graph detail, high-value structured relations can be flattened/lost.

## 5) Recommended Contract Boundary (Target Design)

### Parser-internal boundary (should stay internal)

- Raw OCR tokens, parser hypotheses, arbitration internals, low-level region construction details.
- Intermediate heuristic scores not stable enough for external consumers.

### Contract-level boundary (should be explicit and versioned)

- Grounded site-schematic object model:
  - pages/regions
  - legend+abbreviation+outlet definitions
  - typed rules/requirements
  - symbol instances and links (with status)
  - typed graph nodes/edges with provenance
- Unresolved/conflicting observations as first-class structures.

### OrbitBrief consumption boundary (ideal)

- OrbitBrief consumes:
  - graph-projected canonical facts,
  - explicit unresolved/conflict queues,
  - high-confidence field claims derived from graph, not only packet text.

## 6) Normalization Strategy to Bridge Current -> Target

Short term:

- Keep current `FieldClaim` pipeline for compatibility.
- Add deterministic projection from `SiteSchematicBundle`/graph to explicit claim families with provenance passthrough.

Medium term:

- Define shared contract schemas for site-schematic graph payloads (versioned).
- Make claim projection a downstream view of graph contracts rather than the only contract.

Long term:

- OrbitBrief planners/operators consume graph-first contracts and use claims as convenience summaries.

## 7) Legality, Confidence, and Audit Requirements at Contract Boundary

Must remain explicit across boundaries:

- status (`stated`, `inferred`, `approximate`, `field_verify_required`, `coordination_required`, `owner_furnished`, `unresolved`)
- confidence score
- provenance:
  - packet id
  - page/sheet id
  - region id
  - source modality/provider when applicable
- contradiction groups and review flags

Current capability status:

- Runtime claim ontology and postprocess provide strong audit primitives.
- Site-schematic graph unresolved/conflict modeling needs stronger direct contract exposure.

## 8) Practical Next Move Before Full Model Hookup

- Freeze a `site_schematic_contract_v1` shape in shared contracts that mirrors `SiteSchematicBundle` core graph semantics.
- Add deterministic mapper:
  - `SiteSchematicBundle` -> shared `site_schematic_contract_v1`
  - optional `site_schematic_contract_v1` -> compatibility `FieldClaim[]`
- Keep compatibility with existing claim consumers while enabling graph-native consumers.
