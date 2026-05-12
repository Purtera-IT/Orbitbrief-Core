# Universality Residual Debug Kit v2

This is the **packet-by-packet debug companion** to the residual fix kit.

It is based on the exact remaining 7 failing holdouts after your latest successful pass:
- A = 7/10
- B = 7/10
- C = 6/10
- D = 3/10
- production regressions = 0

## What this kit adds
- one debug sheet per remaining holdout
- exact likely root cause per remaining packet
- fastest packet-fix order to push toward 9/9/8+
- one Cursor prompt to drive the residual pass using packet clusters, not broad rewrites

## Fastest path
The fastest path to:
- A >= 9
- B >= 9
- C >= 8

is likely:
1. `tc_d_appalachian_gym_comms`
2. `tc_e_red_bay_admin_comms`
3. `lv_a_aspen_house_telecom_intercom_risers`
4. `lv_e_columbus_library_technology_security`
5. `tc_b_seele_es_refresh_dwgs`
6. `lv_d_iqaluit_operations_centre`
7. `lv_b_300_progress_communications`

Why:
- Fixing `tc_d` + `tc_e` should move both A and C.
- Fixing `lv_a` + `lv_e` should move B to 9 quickly.
- `tc_b` is likely a tiny provenance-completion edge.
- `lv_b` appears to be the hardest residual B packet and should be saved for last in the current cluster.
