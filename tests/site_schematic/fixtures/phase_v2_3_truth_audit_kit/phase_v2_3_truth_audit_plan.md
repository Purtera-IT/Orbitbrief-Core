# Phase V2.3 truth-audit plan

## Why this pass is needed
The previous V2.2 run almost certainly over-corrected:
- `grounded_symbol_yield_rate = 1.0`
- `unresolved_symbol_ratio = 0.0`
- `room_device_association_rate = 1.0`
- `connector_grounding_quality_rate = 1.0`
- `packet_hardpage_semantics_rate = 1.0`

And packet rows showed patterns like:
- every candidate grounded
- identical `connector_required=true`, `connector_grounding_ok=true`, `room_device_association_ok=true`
- at least one packet with `required_page_types=[]` and `hardpage_rate=1.0`

This strongly suggests:
- default success propagation
- incomplete hard-page requirement enforcement
- over-grounding
- evaluation that is reading success flags rather than evidence

## Objective
Repair V2 so that it is **honest and evidence-backed**, even if that means metrics temporarily go down.

## Fixes in this kit

### 1. Hard-page requirement truth repair
For every packet:
- derive required hard-page types from actual page rows + schema
- if a packet contains legend/riser/equipment/detail/floorplan pages, required types must not be empty
- empty required sets cannot auto-pass

### 2. Evidence-backed association flags
Never allow:
- `connector_grounding_ok = true`
- `room_device_association_ok = true`
- `grounding_state = grounded`
unless those are backed by evidence scores meeting thresholds

### 3. Grounded-yield sanity
Add sanity checks so that:
- packets do not silently auto-ground 100% of candidates
- grounded yield must be consistent with evidence distribution
- unresolved remains allowed and expected when support is weak

### 4. Truth-audit summary
Add packet-level and corpus-level audits:
- suspicious_uniform_grounding
- empty_required_hardpage_sets
- impossible_connector_success
- impossible_room_assoc_success
- state_distribution_by_packet
- evidence score distributions

### 5. Sample row inspection artifacts
Emit sample rows for each packet showing:
- legend_match_score
- legend_text_association_score
- room_device_association_score
- connector_context_score
- page_type_compatibility
- final grounding state
- evidence-backed booleans

## What success looks like
The final metrics may no longer be all 1.0.
That is okay.
What matters is:
- they are honest
- no hidden eval holes remain
- grounded results are actually evidence-backed
- unresolved is present where it should be
- hard-page pass means something real
