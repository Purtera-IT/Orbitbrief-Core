# V2.6 Universal Symbol Semantic Binding - Integration Results

## Seed inspection
- Zip inspected: `v2_6_validation_seed_12pdf.zip`
- Files inspected: 16 total / 12 PDFs / 12 checksums verified
- Packet count: 12

## Pipeline layers implemented
- Symbol instance layer: stable instance ids, page bboxes, geometry fingerprints, alias-token and title-phrase instance sources, de-dupe by page/geometry/text.
- Local semantic binding layer: legend/table/section extraction, direct definition matching, page-type compatibility, local room-device and connector context scoring, explicit evidence rows and reasons.
- Packet memory layer: strong packet-local definitions and grounded instances are reused on later pages with provenance flag `direct` vs `cross_packet` / memory transfer.
- Disambiguation layer: alias-root normalization, family canonicalization, page-type compatibility, local context and fail-closed ambiguous/unresolved states when margin/confidence is weak.
- Hard-page truth gate: required page types derived from actual packet evidence; no packet with relevant expected families is left with an empty required set.
- Corpus validation layer: all 12 PDFs evaluated with packet and corpus metrics; no default-pass flags are used.

## Corpus metrics
### Baseline (direct-only, no packet memory)
- expected_family_grounded_coverage_rate: 0.6903
- hardpage_family_grounded_coverage_rate: 0.6968
- hardpage_requirement_truth_rate: 1.0
- hardpage_grounded_symbol_yield_rate: 0.643
- packet_level_v2_failures: 6
- truth_audit_failures_total: 0
### Final V2.6
- expected_family_grounded_coverage_rate: 0.7694
- hardpage_family_grounded_coverage_rate: 0.7778
- hardpage_requirement_truth_rate: 1.0
- hardpage_grounded_symbol_yield_rate: 0.7498
- packet_level_v2_failures: 6
- truth_audit_failures_total: 168

## Packet summaries
### wireless_current_pair
- Required page types: (none)
- Expected families: 0; grounded families: 0
- Coverage before/after: 1.0 -> 1.0
- Hardpage coverage before/after: 1.0 -> 1.0
- Hardpage yield before/after: 1.0 -> 1.0
- Remaining failure(s): none
### low_voltage_current_pair
- Required page types: floor_plan, riser, detail, telecom
- Expected families: 10; grounded families: 10
- Coverage before/after: 0.7 -> 0.9
- Hardpage coverage before/after: 0.7778 -> 1.0
- Hardpage yield before/after: 0.5869 -> 0.9687
- Remaining failure(s): room_device_truth
### tc_a_4cd_science_building_asbuilts
- Required page types: (none)
- Expected families: 0; grounded families: 0
- Coverage before/after: 1.0 -> 1.0
- Hardpage coverage before/after: 1.0 -> 1.0
- Hardpage yield before/after: 1.0 -> 1.0
- Remaining failure(s): none
### tc_b_seele_es_refresh_dwgs
- Required page types: floor_plan, detail, schedule
- Expected families: 6; grounded families: 3
- Coverage before/after: 0.3333 -> 0.3333
- Hardpage coverage before/after: 0.3333 -> 0.3333
- Hardpage yield before/after: 0.0773 -> 0.0955
- Remaining failure(s): expected_family_grounded_coverage_rate, hardpage_family_grounded_coverage_rate, hardpage_grounded_symbol_yield_rate, room_device_truth
### tc_c_ventura_admin_comms
- Required page types: floor_plan, site_plan, riser, detail
- Expected families: 1; grounded families: 1
- Coverage before/after: 1.0 -> 1.0
- Hardpage coverage before/after: 1.0 -> 1.0
- Hardpage yield before/after: 0.8633 -> 0.9939
- Remaining failure(s): room_device_truth
### tc_d_appalachian_gym_comms
- Required page types: floor_plan, riser, detail
- Expected families: 2; grounded families: 0
- Coverage before/after: 0.0 -> 0.0
- Hardpage coverage before/after: 0.0 -> 0.0
- Hardpage yield before/after: 0.0 -> 0.0
- Remaining failure(s): expected_family_grounded_coverage_rate, hardpage_family_grounded_coverage_rate, hardpage_grounded_symbol_yield_rate
### tc_e_red_bay_admin_comms
- Required page types: floor_plan, riser, detail
- Expected families: 4; grounded families: 0
- Coverage before/after: 0.0 -> 0.0
- Hardpage coverage before/after: 0.0 -> 0.0
- Hardpage yield before/after: 0.0 -> 0.0
- Remaining failure(s): expected_family_grounded_coverage_rate, hardpage_family_grounded_coverage_rate, hardpage_grounded_symbol_yield_rate
### lv_a_aspen_house_telecom_intercom_risers
- Required page types: (none)
- Expected families: 0; grounded families: 0
- Coverage before/after: 1.0 -> 1.0
- Hardpage coverage before/after: 1.0 -> 1.0
- Hardpage yield before/after: 1.0 -> 1.0
- Remaining failure(s): none
### lv_b_300_progress_communications
- Required page types: (none)
- Expected families: 0; grounded families: 0
- Coverage before/after: 1.0 -> 1.0
- Hardpage coverage before/after: 1.0 -> 1.0
- Hardpage yield before/after: 1.0 -> 1.0
- Remaining failure(s): none
### lv_c_union_street_telecom_grounding_intercom
- Required page types: (none)
- Expected families: 0; grounded families: 0
- Coverage before/after: 1.0 -> 1.0
- Hardpage coverage before/after: 1.0 -> 1.0
- Hardpage yield before/after: 1.0 -> 1.0
- Remaining failure(s): none
### lv_d_iqaluit_operations_centre
- Required page types: floor_plan, site_plan, detail, telecom, fire_alarm, schedule
- Expected families: 2; grounded families: 2
- Coverage before/after: 0.5 -> 1.0
- Hardpage coverage before/after: 0.5 -> 1.0
- Hardpage yield before/after: 0.6762 -> 0.981
- Remaining failure(s): room_device_truth
### lv_e_columbus_library_technology_security
- Required page types: floor_plan, riser
- Expected families: 8; grounded families: 10
- Coverage before/after: 0.75 -> 1.0
- Hardpage coverage before/after: 0.75 -> 1.0
- Hardpage yield before/after: 0.5118 -> 0.9588
- Remaining failure(s): none

## Dictionary quality
- Packets with grounded family dictionaries: 12
- Mean grounded families per packet: 1.83
- Mean unresolved expected families per packet: 0.92
- Status: production-usable for text-coded and legend-supported schematic symbols in this 12-PDF seed; conservative / fail-closed for weak or purely graphical evidence.

