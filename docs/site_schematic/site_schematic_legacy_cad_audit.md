# Legacy CAD vs Site Schematic Audit

Scope: files that still influence the `site_schematic` lane or adjacent drawing packet flow.

## 1) Executive Read

- `site_schematic` is present and functional, but **legacy CAD code is still load-bearing** in runtime execution.
- Some `cad_*` files are compatibility-friendly already; others still contain substantive extraction/graph logic that is actively used.
- Immediate deletion of `cad_*` is not safe yet.

## 2) File-by-File Classification

### A) Already acting close to compatibility wrappers

#### `src/orbitbrief_core/parser/adapters/site_schematic_pdf.py`

- Subclasses `CadPdfAdapter`.
- Calls `super().parse(...)` then injects `site_schematic_bundle` metadata.
- Role in migration: adapter-level bridge from CAD parse surface to site-schematic structured output.

#### `src/orbitbrief_core/parser/adapters/site_schematic_image.py`

- Same pattern as PDF variant but for image modality.
- Role in migration: compatibility-preserving bridge.

Note:

- These are not `cad_*` files, but they show current wrapper/bridge style.

### B) Still contains real logic (not wrappers)

#### `src/orbitbrief_core/parser/adapters/cad_pdf.py`

- Performs substantive CAD extraction through `extract_cad_structure`.
- Builds evidence spans and metadata used by runtime packetization and claim extraction.
- Also calls site-schematic bundle build for compatibility/context.
- Status: **load-bearing**.

#### `src/orbitbrief_core/parser/adapters/cad_image.py`

- Image counterpart of `cad_pdf.py`; same load-bearing pattern.
- Status: **load-bearing**.

#### `src/orbitbrief_core/parser/adapters/cad_common.py`

- Core CAD structure and evidence bundle utilities (`extract_cad_structure`, `build_cad_evidence_bundle`).
- Upstream dependency for CAD adapters.
- Status: **load-bearing**.

#### `src/orbitbrief_core/parser/graph/cad_passes.py`

- `CadStructuralPass` injects CAD/site drawing structural edges and strategy hints.
- Invoked in generic graph builder path for CAD/site-like modalities.
- Status: **load-bearing**.

#### `src/orbitbrief_core/parser/graph/cad_signals.py`

- Shared signal computations (`same_sheet`, `near`, overlap-based helpers, component/zone cues).
- Used by CAD graph passes and packetization logic.
- Status: **load-bearing**.

#### `src/orbitbrief_core/runtime_spine/extractors/cad_packet_to_claims.py`

- CAD packet-family claim compiler with bounded assist hooks.
- Active path whenever packet family is one of CAD-specific families.
- Status: **load-bearing**.

### C) Wrapper candidates (future, not now)

#### `cad_pdf.py` / `cad_image.py`

- Candidate to become thin delegates to site-schematic-native parse output **after**:
  - site-schematic graph-first projection fully replaces CAD packet-family claims for drawing lanes,
  - regression suite proves no loss for legacy drawing modalities.

#### `cad_passes.py` / `cad_signals.py`

- Candidate to split:
  - truly generic spatial/lexical signals retained in neutral modules,
  - lane-specific logic moved to `site_schematic/graph/` and invoked directly from site lane.

#### `cad_packet_to_claims.py`

- Candidate to shrink once graph-native site-schematic projection emits contract-ready outputs.

## 3) Compatibility Surface That Must Stay Intact (Current)

Do not break yet:

- Legacy modality names and parser routing that still produce CAD packet families.
- Existing imports that expect `cad_*` adapters and packet extractor modules.
- Runtime graph/packet pipeline assumptions for `drawing_packet` role.

## 4) Safe-to-Deprecate-Later Candidates (Conditional)

These become removable only after graph-first migration completes and tests pass:

- Duplicative CAD extraction heuristics that overlap with `site_schematic/core.py` object builders.
- CAD packet-family claim shims that duplicate site-schematic graph-derived claims.
- CAD-only structural edge heuristics if superseded by site-schematic typed graph edges with equal/better coverage.

## 5) Files Most Likely To Remain Long-Term

- A minimal CAD compatibility facade (routing aliases + adapter indirection).
- Shared low-level utilities that are modality-agnostic (if refactored out of CAD-named modules).

## 6) Deprecation Readiness Checklist

Before reducing/removing `cad_*` in this lane:

1. Site-schematic graph projection must cover all current drawing packet claim families needed downstream.
2. Gold route tests (`wireless` and `low_voltage`) must pass graph and contract assertions.
3. Backward compatibility tests for legacy CAD modality aliases must remain green.
4. Fallback behavior (`intake_only`, review flags) must remain fail-closed.
5. Shared contracts must expose graph-derived unresolved/conflict outputs, not only flattened claims.

## 7) Current Recommendation

- Keep all `cad_*` files in place now.
- Continue reducing duplication by moving lane-specific logic into `site_schematic` modules and making `cad_*` call through.
- Plan a staged deprecation after graph-first contract boundary is in production.
