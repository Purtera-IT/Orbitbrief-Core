---
name: Parser Sandwich Cutover
overview: Create a clean, modular parser->extractor->post-processor pipeline for Orbitbrief professional services, remove legacy duplication, and provide a read-first audit path for implementation and rollout.
todos:
  - id: map-current-vs-target
    content: Document active legacy path vs parser-first path and confirm migration boundaries.
    status: pending
  - id: wire-parser-in-pipeline
    content: Introduce parser-first stage in pipeline and keep ingestors as temporary facade.
    status: pending
  - id: build-extractor-registry
    content: Create role/modality extractor registry and migrate transcript_or_notes text lane first.
    status: pending
  - id: add-post-processor
    content: Implement deterministic post-processor for field/path/type enforcement and dedupe.
    status: pending
  - id: unify-registry-source
    content: Pick YAML or code as parser registry source-of-truth and remove split-brain behavior.
    status: pending
  - id: enforce-strict-fallback
    content: Ensure unsupported flows are intake_only with review flags and no claim generation.
    status: pending
  - id: audit-and-tests
    content: Add migration audit checks and extend tests for parser-contract, legality, and pipeline states.
    status: pending
isProject: false
---

# Parser-First Cutover Plan

## Where We Are Now

- Active runtime path is still legacy: [pipeline.py](src/orbitbrief_core/runtime_spine/pipeline.py) calls [ingestors.py](src/orbitbrief_core/runtime_spine/ingestors.py) directly.
- Parser-first foundation exists but is not on the hot path:
  - [parsers/registry.py](src/orbitbrief_core/runtime_spine/parsers/registry.py)
  - [parsers/professional_services/text_narrative.py](src/orbitbrief_core/runtime_spine/parsers/professional_services/text_narrative.py)
  - [extractors/](src/orbitbrief_core/runtime_spine/extractors)
- Registry split exists:
  - Code registry in [parsers/registry.py](src/orbitbrief_core/runtime_spine/parsers/registry.py)
  - YAML registry in [config/runtime/parsers/parser_registry.yaml](config/runtime/parsers/parser_registry.yaml) (not runtime-loaded yet).

## Read-Through Order (Before Refactor)

- Architecture intent: [ARCHITECTURE.md](src/orbitbrief_core/runtime_spine/ARCHITECTURE.md)
- Runtime orchestration: [pipeline.py](src/orbitbrief_core/runtime_spine/pipeline.py)
- Current ingest behavior: [ingestors.py](src/orbitbrief_core/runtime_spine/ingestors.py)
- New text parser stack:
  - [parsers/professional_services/text_narrative.py](src/orbitbrief_core/runtime_spine/parsers/professional_services/text_narrative.py)
  - [parsers/professional_services/adapters](src/orbitbrief_core/runtime_spine/parsers/professional_services/adapters)
  - [parsers/professional_services/contracts.py](src/orbitbrief_core/runtime_spine/parsers/professional_services/contracts.py)
- Extractor foundations:
  - [extractors/narrative_claim_ontology.py](src/orbitbrief_core/runtime_spine/extractors/narrative_claim_ontology.py)
  - [extractors/narrative_prompt_template.py](src/orbitbrief_core/runtime_spine/extractors/narrative_prompt_template.py)
  - [extractors/narrative_projector.py](src/orbitbrief_core/runtime_spine/extractors/narrative_projector.py)
- Test baseline:
  - [tests/test_planner_and_provenance.py](tests/test_planner_and_provenance.py)
  - [tests/test_transcript_ingestor.py](tests/test_transcript_ingestor.py)
  - [tests/test_text_narrative_foundation.py](tests/test_text_narrative_foundation.py)

## What Should Be Removed or Phased Out

- Phase out legacy ingestion logic as primary extraction engine in [ingestors.py](src/orbitbrief_core/runtime_spine/ingestors.py).
- Remove duplicated text extraction heuristics once parser-first extractor is wired.
- Remove registry split by making one source of truth:
  - Either load YAML registry at runtime or remove YAML and keep code-only registry.
- Remove generic "fake success" extraction behavior and keep strict `intake_only` fallback for unsupported roles/modality combinations.

## Target Modular Architecture

```mermaid
flowchart LR
    fileInput[FileInput] --> modalityGate[ModalityGate]
    modalityGate --> parserRegistry[ParserRegistry]
    parserRegistry --> parsedArtifact[ParsedArtifact]
    parsedArtifact --> extractorRegistry[ExtractorRegistry]
    extractorRegistry --> claimCandidates[FieldClaimCandidates]
    claimCandidates --> postProcessor[DeterministicPostProcessor]
    postProcessor --> validatedClaims[ValidatedFieldClaims]
    validatedClaims --> planner[Planner]
    planner --> reviewDecision[ReviewDecision]
```

## Build Plan (Functional + Modular + Easy Additions)

### 1) Freeze and enforce parser contracts

- Keep and enforce v1 text parser I/O contract in [text_narrative_parser_io_v1.schema.json](config/runtime/parsers/text_narrative_parser_io_v1.schema.json).
- Add runtime contract checks for parser outputs before extraction starts.

### 2) Wire parser-first execution into hot path

- Update [pipeline.py](src/orbitbrief_core/runtime_spine/pipeline.py) to call `ParserRegistry.parse(...)` before extraction.
- Make [ingestors.py](src/orbitbrief_core/runtime_spine/ingestors.py) a thin compatibility facade, then migrate role logic into `extractors/`.

### 3) Build extractor registry by role/modality

- Add an extractor registry parallel to parser registry (role_id + modality => extractor).
- First production extractor target: `transcript_or_notes` text modalities using:
  - parser outputs from [parsers/professional_services/adapters](src/orbitbrief_core/runtime_spine/parsers/professional_services/adapters)
  - ontology from [narrative_claim_ontology.py](src/orbitbrief_core/runtime_spine/extractors/narrative_claim_ontology.py)
  - projector from [narrative_projector.py](src/orbitbrief_core/runtime_spine/extractors/narrative_projector.py)

### 4) Add deterministic post-processor stage

- Implement dedicated post-processor module for:
  - allowed field/path enforcement
  - type normalization (date/boolean/quantity)
  - dedupe + contradiction detection before planner merge
  - mandatory evidence refs per claim
- Keep planner focused on aggregation and contradiction presentation, not raw cleanup.

### 5) Normalize runtime registry ownership

- Decide and enforce one registry source:
  - Preferred: YAML source in [parser_registry.yaml](config/runtime/parsers/parser_registry.yaml), code loads and validates it.
- Ensure parser metadata consistency (all entries include class/module/version/io schema refs where applicable).

### 6) Keep strict fallback semantics

- Unsupported roles/modality should produce `intake_only` + review flags, no business claim extraction.
- Ensure `parked`, `intake_only`, `implemented` states are explicit in pipeline output.

## What Is Extra Right Now (Not Needed on Hot Path Yet)

- Placeholder parsers are acceptable but extra until wired:
  - [pdf_ocr.py](src/orbitbrief_core/runtime_spine/parsers/pdf_ocr.py)
  - [drawing_vector.py](src/orbitbrief_core/runtime_spine/parsers/drawing_vector.py)
- Ontology/prompt/projector files are foundation-only until extractor registry consumes them.

## Audit Checklist (After Refactor)

- `pipeline.py` no longer does role extraction directly via legacy heuristics.
- Every extracted claim has:
  - allowed field path
  - evidence segment reference
  - confidence + status
- No duplicate parsing logic between parser modules and legacy ingestors.
- Registry loaded once, validated once, used everywhere.
- Tests cover:
  - parser contract validity
  - extractor field legality
  - intake-only behavior
  - planner compatibility

## Success Criteria

- Adding a new modality requires only:
  - new adapter/parser module
  - extractor mapping
  - registry entry
  - tests
- No pipeline edits required for each new role/modality after framework is in place.
