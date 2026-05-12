# Residual fix implementation plan

## Current remaining packets
### A blockers
- tc_d_appalachian_gym_comms
- tc_e_red_bay_admin_comms
- lv_d_iqaluit_operations_centre

### B blockers
- lv_a_aspen_house_telecom_intercom_risers
- lv_b_300_progress_communications
- lv_e_columbus_library_technology_security

### C blockers
- tc_b_seele_es_refresh_dwgs
- plus bbox completeness spillover on tc_d / tc_e / lv_d

## Plan

### Residual A pass — titleblock / sheet-archetype repair
Goal:
- raise sheet_type_accuracy/title_block_detection_rate on tc_d, tc_e, lv_d to 1.0

Approach:
- add packet-family titleblock profiles for school/admin/security-heavy public bids
- add bottom-titleblock/footer-title fallback extraction
- improve scoring of sheet number candidates from title/footer rails
- keep current pair frozen

### Residual B pass — table-family alias completion
Goal:
- raise required_table_kind_coverage on lv_a/lv_b/lv_e to 1.0

Approach:
- add holdout-specific table-family aliases/signatures for:
  - telecom/intercom riser schedules
  - security/communications symbol tables
  - door-control / patch-panel / IT-room specs
  - hospitality/public safety schedule blocks
- reduce fallback to generic_grid where row/header signatures are strong

### Residual C pass — provenance + bbox completion
Goal:
- raise locality_provenance and bbox presence to 1.0 on the remaining holdouts

Approach:
- region bbox completion from children/subregions/pseudo-pages/table anchors
- locality provenance completion from parent lineage when omitted
- never silently leave a region without bbox if recoverable
- never silently leave locality ids blank if derivable

## Integration order
1. add helper modules
2. patch `classification/sheet_type.py`
3. patch `universal_table_spine.py`
4. patch `zoning/page_zones.py`
5. patch `core.py`
6. add tests
7. rerun current pair + full holdout Phase D
