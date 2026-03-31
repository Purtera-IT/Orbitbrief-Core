# Runtime Spine v2 Structure

This package now has a parser-first structure intended to replace the legacy mixed
`file_utils.py` + `ingestors.py` flow.

## Target flow

1. `parsers/*` produce deterministic `ParsedArtifact` outputs.
2. `extractors/*` transform parsed artifacts into schema-allowed `FieldClaim` objects.
3. `heads.py` scores and calibrates already-validated extraction outputs.
4. `pipeline.py` orchestrates and persists provenance.

## Main sections

- `parsers/`
  - File-type specific parsers (text, table, pdf text, pdf ocr, drawing, container).
  - Domain-specific parser packs under `parsers/professional_services/`.
  - Text adapters are split by modality in `parsers/professional_services/adapters/`.
- `extractors/`
  - Role-specific extraction modules and intake-only fallback.
- `config/runtime/parsers/`
  - Parser registry and model/provider configuration.

## Legacy modules (to phase out)

- `file_utils.py`
- `ingestors.py`

These remain active for backward compatibility until parser-first modules are fully wired.
