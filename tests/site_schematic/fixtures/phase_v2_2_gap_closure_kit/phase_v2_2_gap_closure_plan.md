# Phase V2.2 gap-closure implementation plan

## Objective
Close the remaining operational gaps in V2 so the system can:
- find legends
- find symbol candidates
- ground a significant portion of them honestly
- connect them to room/device and connector context
- enforce packet hard-page success

## Problems to fix

### 1. Hard-page semantics metric is too forgiving
Packets can score `hardpage_rate = 1.0` with empty required sets.
That is an evaluation hole.

### 2. Grounding-state policy is too conservative
The current pass leaves too many symbols unresolved.
You need stronger but still fail-closed grounded yield.

### 3. Room/device association is too weak
Grounding needs stronger spatial/context links to:
- room labels
- closet / MDF / IDF labels
- detail titles
- local note blocks
- region / pseudo-page context

### 4. Connector / linework grounding is too weak
Symbols on riser/equipment/detail pages need connector-aware scoring:
- leader attachment
- connector continuity
- riser context
- rack/pathway context

### 5. Eval targets are wrong
The eval should now measure:
- grounded_symbol_yield_rate
- hardpage_grounded_symbol_yield_rate
- unresolved_symbol_ratio
- room_device_association_rate
- connector_grounding_quality_rate
- expected_family_grounded_coverage_rate
- hardpage_requirement_completeness

## Fixes in this kit

### A. Hard-page requirement registry
For each packet, enforce non-empty required hard-page types when present:
- legend_symbol
- riser_diagram
- equipment_room_layout
- installation_detail
- floorplan_overall

### B. Grounded-yield metrics
Compute:
- grounded_symbol_yield_rate
- hardpage_grounded_symbol_yield_rate
- unresolved_symbol_ratio
- expected_family_grounded_coverage_rate

### C. Room/device association refinement
Improve association using:
- nearest room/device label
- same region/subregion/pseudo-page
- same detail frame
- same local note / title block context
- leader adjacency when available

### D. Connector-context refinement
Improve grounding score using:
- connector candidates
- leader attachment
- riser context
- rack/runway/pathway context
- equipment-room page compatibility

### E. State policy hardening
Keep fail-closed behavior, but allow `grounded` when combined evidence is truly strong:
- legend match
- legend text association
- connector score
- room/device score
- page type compatibility

### F. Eval hardening
A packet should fail if:
- hardpage requirement set is empty when it should not be
- grounded yield is too low on hard pages
- room/device association is too low
- connector grounding is too low on connector-heavy packets

## Target metrics
Preserve:
- production_kpi_regression_count = 0
- contradiction_lane_separation_rate = 1.0
- V0/V1 stable
- parser text/table coverage stable

Hit:
- grounding_state_honesty_rate >= 0.95
- grounded_symbol_yield_rate >= 0.6
- hardpage_grounded_symbol_yield_rate >= 0.75
- unresolved_symbol_ratio <= 0.4
- room_device_association_rate >= 0.75
- connector_grounding_quality_rate >= 0.9
- expected_family_grounded_coverage_rate >= 0.8
- packet_hardpage_semantics_rate >= 0.9
- packet_level_v2_failures = 0
