# professional_services structure

This domain should be read in three layers:

1. `base/`
   - Always-on common extraction layer for every `professional_services` run.
   - Captures the shared baseline truth before any narrower specialization logic is applied.

2. `roles/` and `injections/`
   - Role-specific evidence lanes such as `transcript_or_notes`, `site_roster_spreadsheet`, `drawing_packet`, `proposal_quote`, and others.
   - Roles decide which modality-specific workbook-derived source schema is active.
   - Injections decide how that role should be interpreted: priorities, noise, review triggers, and normalization rules.

3. `overlays/`
   - Narrower specialization layers such as `wireless`, `telecom`, `audit`, `hardware`, and others.
   - Overlays extend the baseline and the role outputs with additional focus areas and future pack-specific logic.

Read order:

1. `domain.yaml`
2. `base/baseline_fields.yaml`
3. `base/baseline_injection.yaml`
4. `roles/*.yaml`
5. `injections/*.yaml`
6. `overlays/overlay_catalog.yaml`

Shared-contracts pairing:

- `contracts/orbitbrief/professional_services/base/`
  - baseline common PRE/POST schemas
- `contracts/orbitbrief/professional_services/source_schemas/`
  - exact workbook-derived executable field truth
- `contracts/orbitbrief/professional_services/source_specs/`
  - guidance-only special-case contracts

Runtime intent:

`professional_services baseline -> role-specific ingestion -> overlay enrichment -> planner merge`
