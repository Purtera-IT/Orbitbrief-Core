# Packet-by-packet prioritization order

## 1. tc_d_appalachian_gym_comms
- Why now: Fixing this packet likely lifts both Phase A and Phase C at once.
- Dominant blocker: School-style communications title/footer rail is drifting from current titleblock profiles, and one or more sparse regions are emitted without bbox completion.
- Success condition: A pass and C pass on this packet with no current-pair regression.

## 2. tc_e_red_bay_admin_comms
- Why now: Same fix family as TC-D and likely a second fast A+C lift.
- Dominant blocker: Admin-building communications sheets have slightly different titleblock/footer labeling and sparse mixed plan regions missing bbox completion.
- Success condition: A pass and C pass on this packet with no current-pair regression.

## 3. lv_a_aspen_house_telecom_intercom_risers
- Why now: One B-only failure and likely one of the easier table-family alias fixes.
- Dominant blocker: Hospitality/intercom riser packet uses table families that are semantically obvious to humans but still under-routed by the holdout table-family matcher.
- Success condition: B pass on this packet with current-pair Phase 1B still perfect.

## 4. lv_e_columbus_library_technology_security
- Why now: Another B-only packet that should respond to targeted security/tech table-family aliases.
- Dominant blocker: Door-control / technology-security rough-in packet uses schedule/legend/spec structures that are underclassified by the current table-kind router.
- Success condition: B pass on this packet with current-pair Phase 1B still perfect.

## 5. tc_b_seele_es_refresh_dwgs
- Why now: Likely a tiny C-only edge case after the major C gains; a fast cleanup candidate.
- Dominant blocker: One or two note/legend-adjacent objects are getting scoped correctly but still missing a locality id field after fallback routing.
- Success condition: C pass on this packet with no other metric movement.

## 6. lv_d_iqaluit_operations_centre
- Why now: A/C hybrid residual, but likely mostly title-block and bbox completion rather than deep structural failure.
- Dominant blocker: Security-heavy public-sector title blocks drift slightly, and a single near-miss region lacks bbox completion.
- Success condition: A pass and C pass on this packet.

## 7. lv_b_300_progress_communications
- Why now: Likely the hardest remaining B residual because coverage is only 0.5; save for after the easier B wins.
- Dominant blocker: Mixed communications/security packet likely contains the most unfamiliar table-family signatures and therefore falls back to generic_grid too often.
- Success condition: B pass on this packet after the easier B residuals are already fixed.
