# Runtime Extractor Config

This folder defines canonical extractor registration for parser-first runtime dispatch.

## Files

- `extractor_registry.yaml`: canonical extractor declarations for role + modality/discourse coverage.
- `extractor_registry.schema.json`: JSON Schema for strict extractor-registry validation.

## Notes

- YAML is the canonical declarative source for extractor specs.
- Python (`runtime_spine/extractors/registry.py`) validates and materializes that single source into runtime dispatch objects.
- Unsupported or unregistered flows should degrade to the registered `intake_only` lane, not ad hoc claim emission.
- Postprocess legality policy should be sourced from extractor spec and trusted runtime artifacts (compiled pack), not from extractor output payload fields.
