# Residual pass acceptance checklist

## Must preserve
- current-pair canonical Phase B = perfect
- current-pair canonical Phase C = perfect
- production_kpi_regression_count = 0
- contradiction_lane_separation_rate = 1.0

## Target
- Holdout A >= 9/10
- Holdout B >= 9/10
- Holdout C >= 8/10
- Holdout D >= 5/10

## Stretch
- A = 10/10
- B = 10/10
- C >= 9/10
- D > 5/10

## Residual packet goals
- tc_b locality provenance = 1.0
- tc_d title block + sheet accuracy = 1.0, bbox presence = 1.0
- tc_e title block + sheet accuracy = 1.0, bbox presence = 1.0
- lv_d sheet accuracy = 1.0, bbox presence = 1.0
- lv_a table kind coverage = 1.0
- lv_b table kind coverage = 1.0
- lv_e table kind coverage = 1.0
