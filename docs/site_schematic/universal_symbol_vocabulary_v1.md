# Universal Symbol Vocabulary v1

This document defines the first production-grade universal symbol vocabulary pass for `site_schematic`.

The detector vocabulary is intentionally visual-first. Final meaning is packet-local and must be grounded through local legend, local notes, local abbreviations, and decomposition context.

## Tier Hierarchy

- Tier 1 (layout-region modality): `control_table`, `note_block`, `legend_block`, `detail_frame`, `plan_region`, `riser_region`, `rack_region`, `equipment_region`
- Tier 2 (visual-primitive modality): `outlet_marker`, `device_marker`, `camera_marker`, `pathway_marker`, `box_marker`, `rack_marker`, `grounding_marker`, `callout_marker`, `riser_endpoint`, `annotation_token`
- Tier 3 (semantic grounding): packet-local interpretation only

## Spec Source

- Machine-readable source of truth: `src/orbitbrief_core/parser/site_schematic/symbols/vocabulary_spec.json`

## Class Roles

Each class in the JSON spec declares one or more roles:

- `layout_region_class`: region/layout detector class
- `detector_class`: visual detector class candidate
- `annotation_token_class`: visible token family class
- `legend_grounded_semantic_target`: must be finalized only after local grounding

## Merge / Split / Defer Guidance

Per-class strategy is encoded in the JSON spec:

- `training_plan = separate`: train as independent first-pass class
- `training_plan = merge_parent`: collapse into `merge_parent` class for first-pass YOLO training
- `training_plan = defer`: keep in benchmark/spec but defer from first-pass training due to sparsity

## First-Pass Benchmark Focus

Packet-specific high-impact focus classes are encoded in:

- `packet_focus_sets.wireless`
- `packet_focus_sets.low_voltage`

These are consumed by:

- `symbols/benchmark.py` for benchmark seed priorities
- `symbols/export.py` for candidate sidecar metadata (`vocabulary_focus_matched`)

## Integration Points

- Vocabulary loading/classification: `symbols/vocabulary.py`
- First-pass detector map builder: `symbols/detector_class_map.py`
- Candidate export with vocab labels: `symbols/export.py`
- Benchmark seed generation with class hierarchy fields: `symbols/benchmark.py`

## First-Pass Detector Set

The first practical detector label set is derived from vocabulary classes using:

- `training_plan = separate`
- approved `merge_parent` collapses
- packet focus priority (wireless + low_voltage)
- max-class budget tuned for first-pass training

The map is explicit and machine-readable at runtime:

- `build_first_pass_detector_class_map()` returns:
  - selected detector classes (target ~20-35)
  - full `ontology_to_detector` mapping
  - deferred/not-selected classes with reasons

Detector outputs are bridged through:

`detector class -> ontology class context -> primitive detection object -> symbol instance -> deterministic linker -> symbol resolution outcomes -> graph`.

This pass intentionally avoids collapsing packet-local semantics into global labels.
