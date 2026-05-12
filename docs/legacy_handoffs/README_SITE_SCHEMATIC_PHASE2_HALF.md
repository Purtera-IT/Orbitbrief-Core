# Site Schematic Phase 2 Half - Rebuilt Delta

This rebuilt delta restores the repo-integrated **half-transition** for the new `site_schematic` lane.

## What is implemented in this half

- introduces a real `site_schematic` namespace under `src/orbitbrief_core/parser/site_schematic/`
- keeps backward-compatible `cad_*` adapters and routing behavior
- adds a shared `site_schematic_core` layer with:
  - sheet typing
  - overlay typing (`wireless` vs `low_voltage`)
  - page-local zoning
  - page-local observation extraction
- adds new adapters for:
  - `site_schematic_pdf`
  - `site_schematic_image`
- updates parser/extractor registry wiring so the new site-schematic aliases are recognized
- attaches a `site_schematic_bundle` and `site_schematic_summary` into parse metadata
- adds tests for the new half-transition behavior

## Architectural state after merge

- old `cad_*` names still work
- new `site_schematic_*` structure exists
- the lane is no longer conceptually locked to “CAD”
- the bundle is page-local and observation-heavy, not a flattened blob

## What to merge from this delta

- `src/orbitbrief_core/parser/site_schematic/`
- `src/orbitbrief_core/parser/adapters/site_schematic_pdf.py`
- `src/orbitbrief_core/parser/adapters/site_schematic_image.py`
- updated:
  - `src/orbitbrief_core/parser/adapters/cad_pdf.py`
  - `src/orbitbrief_core/parser/adapters/cad_image.py`
  - `src/orbitbrief_core/parser/adapters/__init__.py`
  - `src/orbitbrief_core/parser/adapters/common.py`
  - `src/orbitbrief_core/parser/router.py`
  - `src/orbitbrief_core/parser/registry.py`
  - `src/orbitbrief_core/parser/graph_builder.py`
  - `src/orbitbrief_core/parser/graph/cad_passes.py`
  - `src/orbitbrief_core/parser/packetizer.py`
  - `src/orbitbrief_core/parser/strategies/site_package.py`
  - `src/orbitbrief_core/runtime_spine/package_joiner.py`
  - `config/runtime/parsers/parser_registry.yaml`
  - `config/runtime/extractors/extractor_registry.yaml`
- added planning YAMLs:
  - `config/runtime/extractors/site_schematic/base_site_schematic.yaml`
  - `config/runtime/extractors/site_schematic/wireless_overlay.yaml`
  - `config/runtime/extractors/site_schematic/low_voltage_overlay.yaml`
- tests:
  - `tests/site_schematic/test_core.py`
  - `tests/parser/test_site_schematic_adapter_phase2_half.py`

## Verified tests

Ran:

```bash
pytest tests/parser/test_cad_lane_stage11_1.py \
       tests/parser/test_cad_graph_stage11_5.py \
       tests/parser/test_cad_packetizer_stage11_6.py \
       tests/parser/test_cad_projection_postprocess_stage11_8.py \
       tests/parser/test_cad_extractor_stage11_7.py \
       tests/parser/test_site_schematic_role_binding_stage11_11.py \
       tests/parser/test_site_schematic_adapter_phase2_half.py \
       tests/site_schematic/test_core.py -q
```

Result:
- **29 passed**

## Real PDF smoke validation

See `site_schematic_phase2_half_smoke_results.md` in this package.

## Not done yet in this half

- full symbol dictionary + symbol-to-plan linking
- true legend-to-instance grounding across plan sheets
- specialized sheet-type extractors replacing the older packet-family-heavy path
- richer bbox / geometry localization
- full end-to-end `1000/10` extraction on every sheet

## Best next prompt for Cursor

Apply this delta as the rebuilt **phase-2 half transition**.
Preserve `cad_*` compatibility, but treat `site_schematic_*` as the new primary namespace.
Then continue phase 2b with:
- legend parsing
- symbol linking
- sheet-type-specific extractors
- stronger real-PDF grounding
- better Southern Post sheet typing
