# Phase V2.5 implementation plan

## Current failure pattern
The current V2 truth-audit says:
- `expected_family_grounded_coverage_rate` is too low
- `hardpage_family_grounded_coverage_rate` is too low
- `hardpage_requirement_truth_rate` is failing
- packet-level V2 failures are still all failing

That tells us the next fix is not another broad grounding rewrite.
It is a **packet-local family coverage repair pass**.

## Root cause
The evaluation is likely still measuring against:
- domain-wide family universes
instead of:
- packet-relevant family universes inferred from the packet's own legends, outlet definitions, note text, abbreviations, and page families.

This makes good grounding look artificially weak.

At the same time:
- hard-page required types are not being derived tightly enough from actual sheet families
- grounded-family derivation from local legend text is not strong enough

## Fix strategy

### 1. Packet-relevant expected family derivation
Build expected family sets from actual packet-local evidence:
- legend grounding dictionary entries
- legend entry text
- outlet definition text
- abbreviation text
- page titles / sheet types
- optional grounded rows already present

This yields:
- `packet_expected_families`
- `hardpage_expected_families`

### 2. Hard-page requirement repair
Derive `required_page_types` from:
- actual packet page rows
- schema-supported page types
Then enforce:
- no empty required set if those page families exist

### 3. Grounded-family derivation repair
When a candidate is grounded or ambiguous, derive `grounded_family` more reliably from:
- mapped local legend semantics
- legend text normalization
- outlet definitions
- page-type compatibility
- connector/riser/rack context

The system should not leave family blank or generic when a packet-local semantic label clearly supports it.

### 4. Family coverage truth metrics
Compute and enforce:
- `expected_family_grounded_coverage_rate`
- `hardpage_family_grounded_coverage_rate`
against packet-relevant family sets, not overbroad domain supersets.

### 5. Packet-level hard-page gate
A packet only passes if:
- hard-page required types are truthful
- hard-page grounded yield is strong enough
- hard-page family coverage is strong enough
- hard pages are not empty-set auto-pass cases

## Integration points
Patch likely:
- `models.py`
- `semantic_mapper.py`
- `grounding_resolver.py`
- `core.py`
- `phase_v2_eval.py`

Add helper modules for:
- packet expected family derivation
- hard-page requirement repair
- family coverage truth
- grounded-family derivation
- hard-page gate enforcement

## Success targets
Preserve:
- current pair stability
- V0/V1 stability
- parser text/table/legend coverage
- contradiction-lane separation

Hit:
- `expected_family_grounded_coverage_rate >= 0.75`
- `hardpage_family_grounded_coverage_rate >= 0.8`
- `hardpage_requirement_truth_rate = 1.0`
- `hardpage_grounded_symbol_yield_rate >= 0.65`
- `packet_level_v2_failures = 0`

If this pass works, V2 becomes much closer to being truly usable for your two domains.
