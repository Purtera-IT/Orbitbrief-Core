# Runtime Parser Config

This folder defines parser registration and backend wiring for the parser-first runtime design.

## Files

- `parser_registry.yaml`: canonical parser list, modalities, and backend wiring status.
- `parser_registry.schema.json`: JSON Schema for validating parser registry structure.
- `text_narrative_parser_io_v1.schema.json`: frozen I/O contract for text narrative extraction intake.

## Notes

- Keep parser IDs stable once used in provenance records.
- Keep parser I/O versions immutable; bump version when fields or semantics change.
- YAML is the canonical declarative source for parser specs. Python (`parser/registry.py`) validates and materializes that single source into runtime dispatch objects.
- `strategy_defaults` are parser-spec hints used when a route does not provide an explicit strategy chain; strategy compatibility and fallback policy live in the runtime strategy control plane.
