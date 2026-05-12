# Contradiction Packet Onboarding

This guide documents how to onboard contradiction-rich packets into the dedicated contradiction evaluation lane without changing production truth paths.

## Goal

Keep three lanes separate:

- canonical symbol KPI (`canonical_symbol`)
- additive topology KPI (`additive_topology`)
- contradiction benchmark lane (`contradiction_benchmark`)

## Registry

Use `tests/site_schematic/fixtures/contradiction_packet_registry.json`.

Each packet entry supports:

- `packet_id`, `packet_label`
- `pdf_path`
- `contradiction_manifest_path`
- `symbol_benchmark_path`
- `packet_type`
- `contradiction_richness`
- `onboarding_status`
- `priority`
- `expected_profile_coverage`
- `expected_family_coverage`
- `enabled`

## Manifest Authoring

Generate a starter manifest template:

```bash
python tools/run_contradiction_packet_eval.py template \
  --packet-id "new_packet_id" \
  --packet-label "New Contradiction Packet" \
  --output "tests/site_schematic/fixtures/contradiction_manifest_new_packet.json"
```

Fill scenarios with:

- `taxonomy`
- `expected_outcome` (`contradiction`, `high_priority_review`, `ambiguous`, `safe`)
- `families`
- `profiles`
- `page_indices`
- `required_evidence_fields`
- `notes`

## Validate Registry + Manifests

```bash
python tools/run_contradiction_packet_eval.py validate \
  --registry tests/site_schematic/fixtures/contradiction_packet_registry.json
```

Optional JSON report:

```bash
python tools/run_contradiction_packet_eval.py validate \
  --registry tests/site_schematic/fixtures/contradiction_packet_registry.json \
  --output compiled_artifacts/site_schematic_symbol_detector_phase/contradiction_registry_validate.json
```

## Run Eval

Run all enabled packets:

```bash
python tools/run_contradiction_packet_eval.py eval \
  --registry tests/site_schematic/fixtures/contradiction_packet_registry.json \
  --output compiled_artifacts/site_schematic_symbol_detector_phase/contradiction_registry_eval.json
```

Run a selected subset:

```bash
python tools/run_contradiction_packet_eval.py eval \
  --registry tests/site_schematic/fixtures/contradiction_packet_registry.json \
  --packet-id low_voltage_real_packet_structural
```

## First Recommended Packet Type

Onboard `detail_installation_conflict` packets first. They provide the best early contradiction signal because they are likely to contain topology-backed family-role incompatibilities with bounded locality evidence.
