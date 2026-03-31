# Runtime Parser Config

This folder defines parser registration and backend wiring for the parser-first runtime design.

## Files

- `parser_registry.yaml`: canonical parser list, modalities, and backend wiring status.

## Notes

- `engine_type: deterministic` means no model dependency.
- `engine_type: model_backed` means parser requires an external OCR/vision/vector backend.
- Keep parser IDs stable once used in provenance records.
