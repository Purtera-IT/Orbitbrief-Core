# Universality Residual Fix Kit v1

This kit is the **targeted residual pass** after the latest universality push reached:

- Holdout Phase A: 7/10
- Holdout Phase B: 7/10
- Holdout Phase C: 6/10
- Holdout Phase D packet pass: 3/10
- production regressions: 0

## Why this kit exists
The remaining failures are now **clustered and concrete**, not broad:
- title block / sheet archetype drift on a few packets
- region bbox completeness on a few packets
- locality provenance edge case on one packet
- table-family coverage gaps on three holdout packets

So instead of another broad “universality” pass, this kit gives you:
- a packet-aware residual implementation plan
- patch-style diffs for the exact repo files
- starter helper modules
- tests
- a strict Cursor prompt that says do not stop until the remaining clustered failures are fixed or precisely explained

## Residual target
### Minimum acceptable
- Holdout Phase A >= 9/10
- Holdout Phase B >= 9/10
- Holdout Phase C >= 8/10
- Holdout Phase D >= 5/10
- production regressions remain 0

### Stretch
- A = 10/10
- B = 10/10
- C = 9+/10
- D materially above 5/10

## What this kit attacks directly
### A residual
- `tc_d_appalachian_gym_comms`
- `tc_e_red_bay_admin_comms`
- `lv_d_iqaluit_operations_centre`

### B residual
- `lv_a_aspen_house_telecom_intercom_risers`
- `lv_b_300_progress_communications`
- `lv_e_columbus_library_technology_security`

### C residual
- `tc_b_seele_es_refresh_dwgs`
- plus bbox completeness spillover on `tc_d`, `tc_e`, `lv_d`
