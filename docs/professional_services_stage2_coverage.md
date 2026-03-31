# Professional Services Stage 2 Coverage

This report is derived from workbook-backed Stage 1 source schemas and the Stage 2 runtime support plan.

## drawing_packet

### PDF

- PRE source: `drawing_packet.pdf.pre`
- POST source: `drawing_packet.pdf.post`

| Field | Layer | Support | Notes |
|---|---|---|---|
| `project_type` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `service_category` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `project_summary` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `project_name` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `customer_name` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `end_customer_name` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `site_count` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `location_details` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `site_name` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `site_address` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `drawing_packet_metadata` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `scope_confirmation_by_system` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `site_profile_from_drawings` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `scope_tasks_requested` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `known_quantities` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `customer_provided_materials` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `access_constraints` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `testing_requirements` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `deliverables_needed` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `known_assumptions` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `known_exclusions` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `open_questions` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `room_by_room_scope_matrix` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `device_inventory_by_area` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `distance_takeoff_by_run` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `pathway_and_constructability` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `installation_conditions` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `trade_responsibility_matrix` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `materials_required_by_system` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `materials_bill_of_materials_inputs` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `materials_allowance_model` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `labor_type_requirements` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `automatic_loe_inputs` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `testing_and_closeout_requirements` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `drawing_confidence` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `commercial_flags` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `pricing_risk_signals` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `normalization_notes` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `scope_overview` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `detailed_scope_of_services` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `deliverables` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `assumptions` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `customer_responsibilities` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `out_of_scope` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `risks_or_dependencies` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `completion_criteria` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `open_items` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |

### DWG export PDF

- PRE source: `drawing_packet.dwg_export_pdf.pre`
- POST source: `drawing_packet.dwg_export_pdf.post`

| Field | Layer | Support | Notes |
|---|---|---|---|
| `project_type` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `service_category` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `project_summary` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `project_name` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `customer_name` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `end_customer_name` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `site_count` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `location_details` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `site_name` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `site_address` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `drawing_packet_metadata` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `scope_confirmation_by_system` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `site_profile_from_drawings` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `scope_tasks_requested` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `known_quantities` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `customer_provided_materials` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `access_constraints` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `testing_requirements` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `deliverables_needed` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `known_assumptions` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `known_exclusions` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `open_questions` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `room_by_room_scope_matrix` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `distance_takeoff_by_run` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `pathway_and_constructability` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `installation_conditions` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `materials_required_by_system` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `materials_bill_of_materials_inputs` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `labor_type_requirements` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `automatic_loe_inputs` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `drawing_confidence` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `pricing_risk_signals` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `normalization_notes` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `scope_overview` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `detailed_scope_of_services` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `deliverables` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `assumptions` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `customer_responsibilities` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `out_of_scope` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `risks_or_dependencies` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `completion_criteria` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `open_items` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |

### image PDF

- PRE source: `drawing_packet.image_pdf.pre`
- POST source: `drawing_packet.image_pdf.post`

| Field | Layer | Support | Notes |
|---|---|---|---|
| `project_type` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `service_category` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `project_summary` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `project_name` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `customer_name` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `end_customer_name` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `site_count` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `location_details` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `site_name` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `site_address` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `drawing_packet_metadata` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `image_readability_confidence` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `visual_scope_confirmation_by_system` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `site_profile_from_visuals` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `scope_tasks_requested` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `known_quantities` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `customer_provided_materials` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `access_constraints` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `testing_requirements` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `deliverables_needed` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `known_assumptions` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `known_exclusions` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `open_questions` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `room_by_room_scope_matrix` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `estimated_device_counts_from_visuals` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `distance_takeoff_by_run` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `visual_pathway_and_constructability` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `installation_conditions` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `materials_required_by_system` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `materials_bill_of_materials_inputs` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `labor_type_requirements` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `automatic_loe_inputs` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `testing_and_closeout_requirements` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `commercial_flags` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `pricing_risk_signals` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `normalization_notes` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `scope_overview` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `detailed_scope_of_services` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `deliverables` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `assumptions` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `customer_responsibilities` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `out_of_scope` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `risks_or_dependencies` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `completion_criteria` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `open_items` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |

## site_roster_spreadsheet

### XLSX

- PRE source: `site_roster_spreadsheet.xlsx.pre`
- POST source: `site_roster_spreadsheet.xlsx.post`

| Field | Layer | Support | Notes |
|---|---|---|---|
| `project_type` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `service_category` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `project_summary` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `program_name` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `customer_name` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `end_customer_name` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `global_program_type` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `site_count` | PRE | `direct_extract` | Implemented in Stage 2 ingestor. |
| `location_details` | PRE | `direct_extract` | Implemented in Stage 2 ingestor. |
| `scope_tasks_requested` | PRE | `direct_extract` | Implemented in Stage 2 ingestor. |
| `known_quantities` | PRE | `direct_extract` | Implemented in Stage 2 ingestor. |
| `customer_provided_materials` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `access_constraints` | PRE | `direct_extract` | Implemented in Stage 2 ingestor. |
| `testing_requirements` | PRE | `direct_extract` | Implemented in Stage 2 ingestor. |
| `deliverables_needed` | PRE | `direct_extract` | Implemented in Stage 2 ingestor. |
| `known_assumptions` | PRE | `direct_extract` | Implemented in Stage 2 ingestor. |
| `known_exclusions` | PRE | `direct_extract` | Implemented in Stage 2 ingestor. |
| `open_questions` | PRE | `direct_extract` | Implemented in Stage 2 ingestor. |
| `program_level_delivery_model` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `program_level_commercial_model` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `program_level_schedule` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `rollout_metadata` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `global_assumptions_and_risk_summary` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `site_roster_rows` | PRE | `direct_extract` | Implemented in Stage 2 ingestor. |
| `normalization_notes` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `scope_overview` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `detailed_scope_of_services` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `deliverables` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `assumptions` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `customer_responsibilities` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `out_of_scope` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `risks_or_dependencies` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `completion_criteria` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `open_items` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |

### CSV

- PRE source: `site_roster_spreadsheet.csv.pre`
- POST source: `site_roster_spreadsheet.csv.post`

| Field | Layer | Support | Notes |
|---|---|---|---|
| `project_type` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `service_category` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `project_summary` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `program_name` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `customer_name` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `end_customer_name` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `global_program_type` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `site_count` | PRE | `direct_extract` | Implemented in Stage 2 ingestor. |
| `location_details` | PRE | `direct_extract` | Implemented in Stage 2 ingestor. |
| `scope_tasks_requested` | PRE | `direct_extract` | Implemented in Stage 2 ingestor. |
| `known_quantities` | PRE | `direct_extract` | Implemented in Stage 2 ingestor. |
| `customer_provided_materials` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `access_constraints` | PRE | `direct_extract` | Implemented in Stage 2 ingestor. |
| `testing_requirements` | PRE | `direct_extract` | Implemented in Stage 2 ingestor. |
| `deliverables_needed` | PRE | `direct_extract` | Implemented in Stage 2 ingestor. |
| `known_assumptions` | PRE | `direct_extract` | Implemented in Stage 2 ingestor. |
| `known_exclusions` | PRE | `direct_extract` | Implemented in Stage 2 ingestor. |
| `open_questions` | PRE | `direct_extract` | Implemented in Stage 2 ingestor. |
| `program_level_delivery_model` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `program_level_commercial_model` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `program_level_schedule` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `rollout_metadata` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `global_assumptions_and_risk_summary` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `site_roster_rows` | PRE | `direct_extract` | Implemented in Stage 2 ingestor. |
| `normalization_notes` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `scope_overview` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `detailed_scope_of_services` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `deliverables` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `assumptions` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `customer_responsibilities` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `out_of_scope` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `risks_or_dependencies` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `completion_criteria` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `open_items` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |

### XLS

- PRE source: `site_roster_spreadsheet.xls.pre`
- POST source: `site_roster_spreadsheet.xls.post`

| Field | Layer | Support | Notes |
|---|---|---|---|
| `project_type` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `service_category` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `project_summary` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `program_name` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `customer_name` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `end_customer_name` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `global_program_type` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `site_count` | PRE | `direct_extract` | Implemented in Stage 2 ingestor. |
| `location_details` | PRE | `direct_extract` | Implemented in Stage 2 ingestor. |
| `scope_tasks_requested` | PRE | `direct_extract` | Implemented in Stage 2 ingestor. |
| `known_quantities` | PRE | `direct_extract` | Implemented in Stage 2 ingestor. |
| `customer_provided_materials` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `access_constraints` | PRE | `direct_extract` | Implemented in Stage 2 ingestor. |
| `testing_requirements` | PRE | `direct_extract` | Implemented in Stage 2 ingestor. |
| `deliverables_needed` | PRE | `direct_extract` | Implemented in Stage 2 ingestor. |
| `known_assumptions` | PRE | `direct_extract` | Implemented in Stage 2 ingestor. |
| `known_exclusions` | PRE | `direct_extract` | Implemented in Stage 2 ingestor. |
| `open_questions` | PRE | `direct_extract` | Implemented in Stage 2 ingestor. |
| `program_level_delivery_model` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `program_level_commercial_model` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `program_level_schedule` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `rollout_metadata` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `global_assumptions_and_risk_summary` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `site_roster_rows` | PRE | `direct_extract` | Implemented in Stage 2 ingestor. |
| `normalization_notes` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `scope_overview` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `detailed_scope_of_services` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `deliverables` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `assumptions` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `customer_responsibilities` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `out_of_scope` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `risks_or_dependencies` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `completion_criteria` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `open_items` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |

## transcript_or_notes

### TXT

- PRE source: `transcript_or_notes.txt.pre`
- POST source: `transcript_or_notes.txt.post`

| Field | Layer | Support | Notes |
|---|---|---|---|
| `project_name` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `customer_name` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `end_customer_name` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `request_source` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `project_type` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `service_category` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `business_driver` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `project_summary` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `success_criteria` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `site_count` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `site_locations` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `site_types` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `site_topology` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `site_conditions` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `scope_included` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `scope_excluded` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `scope_by_others` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `known_quantities` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `technical_environment` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `schedule` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `access_and_logistics` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `deliverables_required` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `testing_and_acceptance` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `customer_responsibilities` | PRE | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `customer_inputs_required` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `customer_provided_materials` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `customer_documents_required` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `third_party_dependencies` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `commercial_structure` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `assumptions` | PRE | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `risks` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `open_questions` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `readiness_gaps` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `primary_customer_contact` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `decision_makers` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `notes_for_sow_author` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `scope_overview` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `detailed_scope_of_services` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `deliverables` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `assumptions` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `customer_responsibilities` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `out_of_scope` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `risks_or_dependencies` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `completion_criteria` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `open_items` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |

### DOCX

- PRE source: `transcript_or_notes.docx.pre`
- POST source: `transcript_or_notes.docx.post.alias`

| Field | Layer | Support | Notes |
|---|---|---|---|
| `project_type` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `service_category` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `project_summary` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `site_count` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `location_details` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `scope_tasks_requested` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `known_quantities` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `customer_provided_materials` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `access_constraints` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `testing_requirements` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `deliverables_needed` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `known_assumptions` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `known_exclusions` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `open_questions` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `scope_overview` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `detailed_scope_of_services` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `deliverables` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `assumptions` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `customer_responsibilities` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `out_of_scope` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `risks_or_dependencies` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `completion_criteria` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `open_items` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |

### MD

- PRE source: `transcript_or_notes.md.pre`
- POST source: `transcript_or_notes.md.post`

| Field | Layer | Support | Notes |
|---|---|---|---|
| `project_type` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `service_category` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `project_summary` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `site_count` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `location_details` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `scope_tasks_requested` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `known_quantities` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `customer_provided_materials` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `access_constraints` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `testing_requirements` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `deliverables_needed` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `known_assumptions` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `known_exclusions` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `open_questions` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `scope_overview` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `detailed_scope_of_services` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `deliverables` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `assumptions` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `customer_responsibilities` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `out_of_scope` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `risks_or_dependencies` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `completion_criteria` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `open_items` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |

### pasted notes

- PRE source: `transcript_or_notes.pasted_notes.pre`
- POST source: `transcript_or_notes.pasted_notes.post`

| Field | Layer | Support | Notes |
|---|---|---|---|
| `project_type` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `service_category` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `project_summary` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `site_count` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `location_details` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `scope_tasks_requested` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `known_quantities` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `customer_provided_materials` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `access_constraints` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `testing_requirements` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `deliverables_needed` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `known_assumptions` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `known_exclusions` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `open_questions` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `scope_overview` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `detailed_scope_of_services` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `deliverables` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `assumptions` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `customer_responsibilities` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `out_of_scope` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `risks_or_dependencies` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `completion_criteria` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `open_items` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |

### email export

- PRE source: `transcript_or_notes.email_export.pre`
- POST source: `transcript_or_notes.email_export.post`

| Field | Layer | Support | Notes |
|---|---|---|---|
| `project_type` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `service_category` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `project_summary` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `site_count` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `location_details` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `scope_tasks_requested` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `known_quantities` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `customer_provided_materials` | PRE | `deferred_review_only` | Accounted for in coverage but deferred to later extraction/review stages. |
| `access_constraints` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `testing_requirements` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `deliverables_needed` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `known_assumptions` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `known_exclusions` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `open_questions` | PRE | `heuristic_extract` | Implemented in Stage 2 ingestor. |
| `scope_overview` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `detailed_scope_of_services` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `deliverables` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `assumptions` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `customer_responsibilities` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `out_of_scope` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `risks_or_dependencies` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `completion_criteria` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |
| `open_items` | POST | `pass_through_chunk` | Mapped through chunking/summarization lane without final canonicalization. |

