# Phase V2.4 grounding-enforcement plan

## Why this pass exists
Previous V2 passes proved:
- architecture is right
- legend dictionaries are found
- candidate groups exist
- provenance is preserved

But audits also showed recurring truth problems:
- empty required hard-page sets still passing
- room/device association scoring collapsing into default-ish success
- connector quality looking perfect even when connector evidence is weak
- expected family grounded coverage remaining too low
- evaluation not penalizing family-coverage misses hard enough

## Objective
Make V2.4 enforce the actual domain goal:
> for each packet, can the system find local legends, identify candidate symbols, and ground enough of the expected symbol-family universe with evidence-backed room/device and connector context on the pages that matter?

## Fix areas

### A. Expected-family grounded coverage enforcement
Per packet, compute:
- expected symbol family set from packet schema
- families actually grounded on hard pages
- families actually grounded corpus-wide
- hard-page family coverage
- overall family coverage

Add failure if:
- expected family grounded coverage is too low
- hard-page family coverage is too low

### B. Room/device evidence truth
Room/device association must only be true when supported by:
- a nearby room/device label
- same region / subregion / pseudo-page / detail frame
- leader attachment or local note/title context
- a real score crossing threshold

Add sanity checks:
- fail packet if room/device association rate is 1.0 but score distribution is collapsed near threshold
- fail packet if association is high with almost no evidence sources

### C. Connector evidence truth
Connector grounding must only be true when supported by:
- connector candidates
- leader attachments
- riser/rack/pathway context
- actual connector context score crossing threshold

Add sanity checks:
- fail packet if connector quality is high while connector evidence is sparse or absent
- require connector grounding especially on hard pages where connectors matter

### D. Hard-page fail counting truth
For every packet:
- derive required hard-page types from actual page rows and schema
- required set cannot be empty when the sheet types exist
- packet hard-page pass should fail if:
  - required set is empty when it should not be
  - grounded yield on hard pages is too low
  - family coverage on hard pages is too low
  - connector/room evidence truth is weak on required pages

### E. Sample-row evidence audits
Emit sample rows per packet with raw evidence:
- legend_match_score
- legend_text_association_score
- room_device_association_score
- connector_context_score
- page_type_compatibility
- final grounding_state
- connector_grounding_ok
- room_device_association_ok
- grounded_family

These are critical. They prevent silent metric cheating.

## Integration points
Patch likely:
- `models.py`
- `semantic_mapper.py`
- `grounding_resolver.py`
- `core.py`
- `phase_v2_eval.py`

Add helper modules for:
- family coverage enforcement
- room/device evidence audit
- connector evidence audit
- hard-page gate enforcement
- sample-row auditing

## Preserve
- parser text/table/legend pipeline
- V0/V1 stability
- contradiction lane separation
- current pair stability

## Targets
Strong enough V2.4 means:
- `expected_family_grounded_coverage_rate >= 0.75`
- `hardpage_family_grounded_coverage_rate >= 0.8`
- `room_device_evidence_truth_rate >= 0.9`
- `connector_evidence_truth_rate >= 0.9`
- `hardpage_requirement_truth_rate = 1.0`
- `hardpage_grounded_symbol_yield_rate >= 0.65`
- `grounding_state_honesty_rate >= 0.95`
- `packet_level_v2_failures = 0`
- `truth_audit_failures_total = 0`
