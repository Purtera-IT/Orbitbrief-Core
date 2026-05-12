# Phase V0/V1 perfection plan

## Objective
Take the current V0/V1 stack from “strong first pass” to “packet-level 10/10-ready”.

## Why this pass is needed
Fast corpus metrics alone are not enough.
To really trust V0/V1, you need:
- packet-level honesty
- raster-heavy sanity
- primitive candidate validation
- graph health checks
- no hidden weak packets behind corpus averages

## What changes
### 1. V0 modality calibration
Add:
- downgrade rules when `vector_rich` is too optimistic
- downgrade rules when `raster_heavy` is too optimistic
- ambiguity flags on mixed-signal pages
- packet-level modality summaries

### 2. V1 primitive validation
Add:
- primitive validation
- leader/connector/dimension quality scoring
- validated primitive counts
- no provenance loss

### 3. Primitive graph quality summaries
Add:
- packet-level primitive graph summaries
- packet-level modality fail counts
- packet-level primitive graph fail counts

### 4. Eval hardening
Upgrade the V0/V1 eval harness to enforce:
- packet-level pass/fail
- packet-level ambiguity visibility
- packet-level weak-page visibility

## Success criteria
### Preserve
- current pair parser truth path stable
- production regressions = 0
- contradiction lane separation = 1.0

### V0
- modality_honesty_rate = 1.0
- current-pair hard-page modality consistency = 1.0
- holdout routing completeness = 1.0
- packet-level modality failures = 0

### V1
- vector_bbox_presence_rate = 1.0
- primitive_provenance_rate = 1.0
- primitive_graph_construction_rate = 1.0
- leader_candidate_presence_on_expected_pages >= 0.95
- dimension_candidate_presence_on_expected_pages >= 0.9
- packet-level primitive graph failures = 0
