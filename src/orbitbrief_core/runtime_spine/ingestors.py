from __future__ import annotations

"""Legacy mixed extraction module.

New extraction modules should live under `runtime_spine/extractors/` and consume
`runtime_spine/parsers/ParsedArtifact`.
"""

import re
from pathlib import Path
from typing import Any

from .config import allowed_business_fields, executable_pre_schema_ref, post_schema_ref, role_runtime_status
from .contracts import BoundingBox, DiagramEdge, DiagramNode, EvidenceChunk, FieldClaim, ImageCrop, ReviewFlag, RoleGraph, RowObject, SheetObject, SourceRef, TableObject
from .file_utils import extract_pdf_text, load_csv_rows, load_xlsx_rows, pdf_page_count, read_textual_file, sha256_file, simple_header_normalize, split_paragraphs, text_lines
from .extractors import InternalNarrativeClaim, intake_only_result, project_to_post_hints, project_to_rich_txt_pre, project_to_slim_pre
from .mapping import resolve_alias
from .mapping_models import HeaderBundle, HeaderPosition, ValueProfile
from .parsers import ParserRegistry
from .shared import make_id, normalize_whitespace, utc_now


def _source_ref(path: Path, schema_ref: str | None = None) -> SourceRef:
    return SourceRef(
        artifact_id=path.stem,
        artifact_name=path.name,
        artifact_path=str(path),
        artifact_hash=sha256_file(path),
        schema_ref=schema_ref,
    )


def _assert_allowed(field_name: str, allowed: list[str], schema_ref: str) -> None:
    if field_name not in allowed:
        raise ValueError(f"Field {field_name!r} is not allowed by schema {schema_ref}")


def _claim(role_id: str, modality: str, schema_ref: str, field_name: str, value: Any, evidence_refs: list[str], target_layer: str) -> FieldClaim:
    allowed = allowed_business_fields(schema_ref)
    _assert_allowed(field_name, allowed, schema_ref)
    return FieldClaim(
        id=make_id("claim"),
        domain_id="professional_services",
        role_id=role_id,
        modality=modality,
        target_layer=target_layer,  # type: ignore[arg-type]
        field_name=field_name,
        field_path=field_name,
        candidate_value=value,
        normalized_value=value,
        schema_ref=schema_ref,
        evidence_refs=evidence_refs,
        confidence=0.6 if target_layer == "pre_field" else 0.55,
        claim_status="asserted" if target_layer == "pre_field" else "inferred",
        created_at=utc_now(),
    )


def _extract_labeled_list(lines: list[str], patterns: list[str]) -> list[str]:
    out = []
    for line in lines:
        lower = line.lower()
        if any(p in lower for p in patterns):
            out.append(line)
    return out


def _looks_like_date(value: str) -> bool:
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}$", value)) or bool(re.match(r"^\d{1,2}/\d{1,2}/\d{2,4}$", value))


def _infer_value_profile(values: list[str]) -> ValueProfile:
    non_empty = [v for v in values if str(v).strip()]
    if not non_empty:
        return ValueProfile(dominant_type="empty", distinct_ratio=0.0, null_ratio=1.0)
    looks_like_date = sum(1 for v in non_empty if _looks_like_date(v)) / len(non_empty) > 0.6
    looks_like_count = sum(1 for v in non_empty if re.fullmatch(r"\d+", str(v).strip())) / len(non_empty) > 0.6
    dominant_type = "text"
    if looks_like_date:
        dominant_type = "date"
    elif looks_like_count:
        dominant_type = "count"
    elif sum(1 for v in non_empty if re.fullmatch(r"[A-Za-z0-9_-]+", str(v).strip())) / len(non_empty) > 0.6:
        dominant_type = "alphanumeric_id"
    distinct_ratio = len(set(non_empty)) / len(non_empty)
    null_ratio = 1 - (len(non_empty) / max(1, len(values)))
    return ValueProfile(
        dominant_type=dominant_type,
        distinct_ratio=round(distinct_ratio, 3),
        null_ratio=round(null_ratio, 3),
        looks_like_date=looks_like_date,
        looks_like_count=looks_like_count,
    )


def _set_path(container: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    current: Any = container
    for idx, part in enumerate(parts):
        is_last = idx == len(parts) - 1
        if part.endswith("[]"):
            key = part[:-2]
            current.setdefault(key, [])
            if is_last:
                if isinstance(value, list):
                    current[key].extend(v for v in value if v not in (None, "", []))
                elif value not in (None, "", []):
                    current[key].append(value)
                return
            if not current[key]:
                current[key].append({})
            current = current[key][0]
        else:
            if is_last:
                current[part] = value
            else:
                current.setdefault(part, {})
                current = current[part]


def _split_city_state_zip(value: str) -> dict[str, str]:
    parts = [part.strip() for part in re.split(r",|\s{2,}", value) if part.strip()]
    out = {}
    if len(parts) >= 1:
        out["city"] = parts[0]
    if len(parts) >= 2:
        state_zip = parts[1].split()
        if state_zip:
            out["state_or_province"] = state_zip[0]
        if len(state_zip) > 1:
            out["postal_code"] = state_zip[1]
    return out


def _role_modality_label(role_id: str, modality: str) -> str:
    if role_id == "transcript_or_notes":
        if modality in {"txt", "md", "docx"}:
            return modality.upper()
        return {"pasted_notes": "pasted notes", "email_export": "email export"}.get(modality, modality)
    if role_id == "drawing_packet":
        return "PDF" if modality == "pdf" else ("DWG export PDF" if modality == "dwg_export_pdf" else "image PDF")
    return modality.upper() if modality in {"csv", "xls", "xlsx", "pdf", "txt", "md", "docx"} else modality


def _parsed_blocks_to_evidence(
    role_id: str,
    modality: str,
    source_ref: SourceRef,
    parsed_blocks: list[Any],
    parser_ref: str,
) -> list[EvidenceChunk]:
    evidence: list[EvidenceChunk] = []
    for block in parsed_blocks:
        raw_text = block.text or ""
        evidence.append(
            EvidenceChunk(
                id=make_id("chunk"),
                domain_id="professional_services",
                role_id=role_id,
                modality=modality,
                content_kind=block.block_type,
                raw_text=raw_text,
                normalized_text=block.normalized_text or normalize_whitespace(raw_text),
                source_ref=source_ref,
                token_estimate=max(1, len(raw_text.split())) if raw_text else 0,
                signal_tags=list(block.tags),
                negative_signal_tags=[],
                parser_refs=[parser_ref],
                confidence=min(1.0, max(0.0, block.confidence)),
                created_at=utc_now(),
            )
        )
    return evidence


def _intake_only_from_parsed(role_id: str, path: Path, modality: str, parsed_artifact: Any | None, reason: str) -> dict[str, Any]:
    source_ref = _source_ref(path)
    evidence: list[Any] = []
    if parsed_artifact is not None:
        parser_ref = f"{parsed_artifact.parser_id}:{parsed_artifact.parser_version}"
        evidence.extend(_parsed_blocks_to_evidence(role_id, modality, source_ref, parsed_artifact.blocks, parser_ref))
    parsed_for_flags = parsed_artifact
    if parsed_for_flags is None:
        # Minimal shim so intake_only_result can report parsed block count.
        from .parsers.models import ParsedArtifact

        parsed_for_flags = ParsedArtifact(
            parser_id="none",
            parser_version="0.0.0",
            role_hint=role_id,
            modality=modality,
            source_path=str(path),
            source_hash=source_ref.artifact_hash,
            blocks=[],
            metadata={},
        )
    extraction = intake_only_result(role_id, modality, parsed_for_flags, reason)
    role_graph = RoleGraph(
        id=make_id("role_graph"),
        domain_id="professional_services",
        role_id=role_id,
        modality=modality,
        source_artifact_id=path.stem,
        source_ref=source_ref,
        evidence_refs=[obj.id for obj in evidence],
        field_claim_refs=[],
        review_flag_refs=[flag.id for flag in extraction.review_flags],
        summary=f"Intake-only fallback executed for {role_id}/{modality}.",
        confidence=0.2,
        created_at=utc_now(),
    )
    return {"evidence_objects": evidence, "field_claims": [], "review_flags": extraction.review_flags, "role_graph": role_graph}


def ingest_transcript_or_notes(path: Path, modality: str) -> dict[str, Any]:
    role_id = "transcript_or_notes"
    modality_label = _role_modality_label(role_id, modality)
    pre_ref = executable_pre_schema_ref(role_id, modality_label)
    post_ref = post_schema_ref(role_id, modality_label)
    source_ref = _source_ref(path, schema_ref=pre_ref)
    parsed = ParserRegistry().parse(path, modality, role_hint=role_id)
    parser_ref = f"{parsed.parser_id}:{parsed.parser_version}"
    evidence = _parsed_blocks_to_evidence(role_id, modality, source_ref, parsed.blocks, parser_ref)

    evidence_refs = [chunk.id for chunk in evidence]
    claims: list[FieldClaim] = []
    review_flags: list[ReviewFlag] = []
    normalized_lines = [block.normalized_text or "" for block in parsed.blocks if (block.text or "").strip()]
    first_text = next((block.text for block in parsed.blocks if (block.text or "").strip()), "") or ""

    internal_claims: list[InternalNarrativeClaim] = []
    if first_text:
        internal_claims.append(InternalNarrativeClaim(claim_family="project_summary", value=first_text, confidence=0.8, evidence_refs=evidence_refs[:1]))

    claim_patterns = {
        "assumption_claim": ["assumption", "assume"],
        "scope_excluded_claim": ["exclusion", "out of scope", "not included"],
        "open_question_claim": ["?", "open question", "tbd"],
        "scope_included_claim": ["install", "replace", "migrate", "refresh", "scope", "task"],
        "deliverable_claim": ["deliverable", "report", "drawing", "closeout"],
        "testing_acceptance_claim": ["test", "certify", "validation"],
        "access_logistics_claim": ["escort", "badge", "access", "after hours"],
        "site_location_claim": ["site", "location", "address", "floor", "room"],
    }
    for family, patterns in claim_patterns.items():
        hits = [block.text for block in parsed.blocks if block.text and any(p in (block.normalized_text or "").lower() for p in patterns)]
        if hits:
            internal_claims.append(InternalNarrativeClaim(claim_family=family, value=hits[:10], confidence=0.72, evidence_refs=evidence_refs))
    quantity_hits: list[str] = []
    for line in normalized_lines:
        quantity_hits.extend(re.findall(r"\b\d+\s+(?:sites?|drops?|aps?|switches?|rooms?|racks?)\b", line, flags=re.I))
    if quantity_hits:
        internal_claims.append(InternalNarrativeClaim(claim_family="known_quantity_claim", value=quantity_hits[:20], confidence=0.7, evidence_refs=evidence_refs))

    pre_payload = project_to_rich_txt_pre(internal_claims) if modality == "txt" else project_to_slim_pre(internal_claims)
    post_payload = project_to_post_hints(internal_claims)

    for field_name, value in pre_payload.items():
        if field_name in allowed_business_fields(pre_ref) and value not in (None, "", [], {}):
            claims.append(_claim(role_id, modality, pre_ref, field_name, value, evidence_refs, "pre_field"))
    for field_name, value in post_payload.items():
        if field_name in allowed_business_fields(post_ref) and value not in (None, "", [], {}):
            claims.append(_claim(role_id, modality, post_ref, field_name, value, evidence_refs, "post_hint"))

    if modality == "docx" and post_ref.endswith(".alias"):
        review_flags.append(
            ReviewFlag(
                id=make_id("review"),
                domain_id="professional_services",
                role_id=role_id,
                modality=modality,
                severity="low",
                code="docx_post_alias_used",
                message="DOCX POST claims used the configured alias because workbook cell C8 has no comment.",
                evidence_refs=evidence_refs,
                created_at=utc_now(),
            )
        )

    role_graph = RoleGraph(
        id=make_id("role_graph"),
        domain_id="professional_services",
        role_id=role_id,
        modality=modality,
        source_artifact_id=path.stem,
        source_ref=source_ref,
        evidence_refs=evidence_refs,
        field_claim_refs=[claim.id for claim in claims],
        review_flag_refs=[flag.id for flag in review_flags],
        summary="Transcript/notes narrative lane ingested into chunk and field-claim outputs.",
        confidence=0.72,
        created_at=utc_now(),
    )
    return {"evidence_objects": evidence, "field_claims": claims, "review_flags": review_flags, "role_graph": role_graph}


def ingest_site_roster_spreadsheet(path: Path, modality: str) -> dict[str, Any]:
    role_id = "site_roster_spreadsheet"
    source_ref = _source_ref(path)
    claims: list[FieldClaim] = []
    review_flags: list[ReviewFlag] = []
    evidence: list[Any] = []
    rows_out: list[RowObject] = []
    mapping_decision_refs: list[str] = []
    candidate_observation_refs: list[str] = []
    pipeline_run_id = make_id("mapping_run")
    pre_ref = executable_pre_schema_ref(role_id, modality.upper())
    post_ref = post_schema_ref(role_id, modality.upper())
    if modality == "xls":
        review_flags.append(
            ReviewFlag(
                id=make_id("review"),
                domain_id="professional_services",
                role_id=role_id,
                modality=modality,
                severity="high",
                code="xls_not_yet_supported",
                message="XLS spreadsheets are explicitly recognized but not yet parsed in Stage 2.",
                requires_human=True,
                created_at=utc_now(),
            )
        )
        role_graph = RoleGraph(
            id=make_id("role_graph"),
            domain_id="professional_services",
            role_id=role_id,
            modality=modality,
            source_artifact_id=path.stem,
            source_ref=source_ref,
            review_flag_refs=[flag.id for flag in review_flags],
            summary="XLS recognized but routed to explicit unsupported-yet review path.",
            confidence=0.15,
            created_at=utc_now(),
        )
        return {"evidence_objects": [], "field_claims": [], "review_flags": review_flags, "role_graph": role_graph}

    if modality == "csv":
        headers, rows = load_csv_rows(path)
        sheet_name = "csv"
    else:
        sheet_name, headers, rows = load_xlsx_rows(path)

    table = TableObject(
        id=make_id("table"),
        domain_id="professional_services",
        role_id=role_id,
        modality=modality,
        source_ref=source_ref,
        page_ref_or_sheet_ref={"index": 1, "name": sheet_name, "kind": "sheet"},
        headers_raw=headers,
        headers_normalized=[simple_header_normalize(h) for h in headers],
        column_count=len(headers),
        confidence=0.9,
        created_at=utc_now(),
    )
    evidence.append(table)

    normalized_headers = [simple_header_normalize(h) for h in headers]
    header_bundles: list[HeaderBundle] = []
    for idx, header in enumerate(headers):
        sample_values = [row.get(header, "") for row in rows[:10]]
        neighbors = []
        if idx > 0:
            neighbors.append(headers[idx - 1])
        if idx + 1 < len(headers):
            neighbors.append(headers[idx + 1])
        header_bundles.append(
            HeaderBundle(
                role_id=role_id,
                domain_id="professional_services",
                modality=modality,
                header_raw=header,
                header_normalized=simple_header_normalize(header).replace("_", " "),
                sheet_name=sheet_name,
                neighbor_headers=neighbors,
                sample_values=[str(v) for v in sample_values if str(v).strip()],
                value_profile=_infer_value_profile([str(v) for v in sample_values]),
                header_position=HeaderPosition(sheet_index=1, column_index=idx + 1),
            )
        )

    alias_results = [resolve_alias(bundle, pipeline_run_id=pipeline_run_id, file_fingerprint=source_ref.artifact_hash) for bundle in header_bundles]
    alias_map = {bundle.header_raw: result for bundle, result in zip(header_bundles, alias_results)}
    for result in alias_results:
        mapping_decision_refs.append(result.decision.mapping_decision_id)
        if result.candidate_observation:
            candidate_observation_refs.append(result.candidate_observation.observation_id)
        if result.decision.review_required:
            review_flags.append(
                ReviewFlag(
                    id=make_id("review"),
                    domain_id="professional_services",
                    role_id=role_id,
                    modality=modality,
                    severity="medium",
                    code="header_mapping_review_required",
                    message=f"Header '{result.decision.header_raw}' did not auto-map cleanly.",
                    requires_human=True,
                    created_at=utc_now(),
                )
            )

    normalized_site_rows: list[dict[str, Any]] = []
    for idx, row in enumerate(rows):
        normalized_site = {}
        row_obj = RowObject(
            id=make_id("row"),
            domain_id="professional_services",
            role_id=role_id,
            modality=modality,
            source_ref=source_ref,
            parent_table_id=table.id,
            row_index=idx,
            raw_cells=row,
            normalized_cells={simple_header_normalize(k): v for k, v in row.items()},
            row_type="site_row" if any(v for v in row.values()) else "empty",
            entity_keys=[],
            confidence=0.85,
            created_at=utc_now(),
        )
        rows_out.append(row_obj)
        evidence.append(row_obj)
        for header, value in row.items():
            result = alias_map.get(header)
            if not result or result.decision.decision_type != "accepted" or not result.decision.target_path:
                continue
            target_path = result.decision.target_path
            if target_path == "__ignore__":
                continue
            if target_path == "site_count":
                continue
            if target_path == "__note_sink__":
                for sink in (result.approved_alias.note_sink_targets if result.approved_alias else []):
                    if value:
                        _set_path(normalized_site, sink.replace("site_roster_rows[].", ""), value)
                continue
            if result.approved_alias and result.approved_alias.mapping_kind == "multi_field_split":
                split_values = _split_city_state_zip(str(value))
                for split_target in result.approved_alias.split_targets:
                    leaf = split_target.replace("site_roster_rows[].", "")
                    field_name = leaf.split(".")[-1]
                    if field_name in split_values:
                        _set_path(normalized_site, leaf, split_values[field_name])
                continue
            if target_path.startswith("site_roster_rows[]."):
                _set_path(normalized_site, target_path.replace("site_roster_rows[].", ""), value)
        if normalized_site:
            normalized_site_rows.append(normalized_site)
    table.row_refs = [row.id for row in rows_out]

    if "site_count" in allowed_business_fields(pre_ref):
        summary_alias = next((result for result in alias_results if result.decision.target_path == "site_count" and result.decision.decision_type == "accepted"), None)
        site_count_value = None
        if summary_alias:
            header = summary_alias.decision.header_raw
            for row in rows:
                val = str(row.get(header, "")).strip()
                if re.fullmatch(r"\d+", val):
                    site_count_value = int(val)
                    break
        if site_count_value is None:
            site_count_value = len(normalized_site_rows) or len(rows_out)
        claims.append(_claim(role_id, modality, pre_ref, "site_count", site_count_value, [table.id], "pre_field"))
    if "site_roster_rows" in allowed_business_fields(pre_ref) and normalized_site_rows:
        claims.append(_claim(role_id, modality, pre_ref, "site_roster_rows", normalized_site_rows, [row.id for row in rows_out], "pre_field"))
    if "location_details" in allowed_business_fields(pre_ref):
        details = []
        for row in normalized_site_rows:
            for key in ("site_name", "address_line_1", "city", "state_or_province", "postal_code", "country"):
                if row.get(key):
                    details.append(str(row.get(key)))
        if details:
            claims.append(_claim(role_id, modality, pre_ref, "location_details", details[:50], [row.id for row in rows_out], "pre_field"))
    if "known_quantities" in allowed_business_fields(pre_ref):
        quantity_map = []
        for header, result in alias_map.items():
            if result.decision.decision_type == "accepted" and result.decision.target_path and "quantity" in result.decision.target_path:
                for row in rows:
                    value = row.get(header)
                    if value:
                        quantity_map.append({result.decision.target_path: value})
        if quantity_map:
            claims.append(_claim(role_id, modality, pre_ref, "known_quantities", quantity_map[:50], [row.id for row in rows_out], "pre_field"))
    joined_notes = [str(value) for row in rows for value in row.values() if str(value).strip()]
    mapping = {
        "scope_tasks_requested": ["scope", "task", "install", "replace", "migration"],
        "access_constraints": ["access", "escort", "badge"],
        "testing_requirements": ["test", "cert"],
        "deliverables_needed": ["deliverable", "report"],
        "known_assumptions": ["assumption"],
        "known_exclusions": ["exclusion", "out of scope"],
        "open_questions": ["question", "?"],
    }
    for field_name, patterns in mapping.items():
        if field_name in allowed_business_fields(pre_ref):
            hits = [note for note in joined_notes if any(p in note.lower() for p in patterns)]
            if hits:
                claims.append(_claim(role_id, modality, pre_ref, field_name, hits[:20], [row.id for row in rows_out], "pre_field"))

    if "scope_overview" in allowed_business_fields(post_ref):
        claims.append(_claim(role_id, modality, post_ref, "scope_overview", f"{len(rows_out)} site rows parsed from {modality.upper()} roster.", [table.id], "post_hint"))
    if "open_items" in allowed_business_fields(post_ref):
        open_hits = [note for note in joined_notes if "?" in note]
        if open_hits:
            claims.append(_claim(role_id, modality, post_ref, "open_items", open_hits[:20], [row.id for row in rows_out], "post_hint"))

    role_graph = RoleGraph(
        id=make_id("role_graph"),
        domain_id="professional_services",
        role_id=role_id,
        modality=modality,
        source_artifact_id=path.stem,
        source_ref=source_ref,
        evidence_refs=[obj.id for obj in evidence if hasattr(obj, "id")],
        field_claim_refs=[claim.id for claim in claims],
        review_flag_refs=[flag.id for flag in review_flags],
        summary=f"Spreadsheet roster ingested into table/row evidence lane with alias-driven header mapping ({len(alias_results)} headers evaluated).",
        confidence=0.84,
        created_at=utc_now(),
    )
    return {
        "evidence_objects": evidence,
        "field_claims": claims,
        "review_flags": review_flags,
        "role_graph": role_graph,
        "mapping_decisions": [result.decision for result in alias_results],
        "candidate_observations": [result.candidate_observation for result in alias_results if result.candidate_observation],
    }


def ingest_drawing_packet(path: Path, modality: str) -> dict[str, Any]:
    role_id = "drawing_packet"
    pre_ref = executable_pre_schema_ref(role_id, "PDF" if modality == "pdf" else ("DWG export PDF" if modality == "dwg_export_pdf" else "image PDF"))
    post_ref = post_schema_ref(role_id, "PDF" if modality == "pdf" else ("DWG export PDF" if modality == "dwg_export_pdf" else "image PDF"))
    source_ref = _source_ref(path, schema_ref=pre_ref)
    text = extract_pdf_text(path)
    page_count = pdf_page_count(path)
    sheets: list[SheetObject] = []
    evidence: list[Any] = []
    image_crops: list[ImageCrop] = []
    claims: list[FieldClaim] = []
    review_flags: list[ReviewFlag] = [
        ReviewFlag(
            id=make_id("review"),
            domain_id="professional_services",
            role_id=role_id,
            modality=modality,
            severity="medium",
            code="drawing_packet_32b_policy_required",
            message="Drawing packet policy requires 32B review, but Stage 2 only records the gate and does not call a model.",
            requires_32b=True,
            created_at=utc_now(),
        )
    ]

    chunks = split_paragraphs(text) or [normalize_whitespace(text)]
    for page_idx in range(1, page_count + 1):
        sheet = SheetObject(
            id=make_id("sheet"),
            domain_id="professional_services",
            role_id=role_id,
            modality=modality,
            source_ref=source_ref,
            page_or_sheet_index=page_idx,
            page_or_sheet_name=f"page_{page_idx}",
            sheet_kind="drawing_page",
            title_block={"title": next((line for line in text_lines(text) if "title" in line.lower() or "drawing" in line.lower()), None)},
            revision_block={"revision": next((line for line in text_lines(text) if "rev" in line.lower()), None)},
            confidence=0.6,
            created_at=utc_now(),
        )
        sheets.append(sheet)
        evidence.append(sheet)
        crop = ImageCrop(
            id=make_id("crop"),
            domain_id="professional_services",
            role_id=role_id,
            modality=modality,
            source_ref=source_ref,
            parent_sheet_id=sheet.id,
            crop_kind="full_page_placeholder",
            bbox=BoundingBox(x0=0, y0=0, x1=1000, y1=1000),
            derived_text=text[:200] if text else None,
            confidence=0.25,
            created_at=utc_now(),
        )
        image_crops.append(crop)
        evidence.append(crop)
    for paragraph in chunks[:page_count or 1]:
        chunk = EvidenceChunk(
            id=make_id("chunk"),
            domain_id="professional_services",
            role_id=role_id,
            modality=modality,
            content_kind="pdf_page_text",
            raw_text=paragraph,
            normalized_text=normalize_whitespace(paragraph),
            source_ref=source_ref,
            token_estimate=max(1, len(paragraph.split())),
            signal_tags=[],
            negative_signal_tags=[],
            parser_refs=["pdf_text_scanner.v1"],
            confidence=0.55,
            created_at=utc_now(),
        )
        evidence.append(chunk)
    evidence_refs = [obj.id for obj in evidence if hasattr(obj, "id")]

    def maybe_claim(field_name: str, value: Any) -> None:
        if field_name in allowed_business_fields(pre_ref) and value:
            claims.append(_claim(role_id, modality, pre_ref, field_name, value, evidence_refs, "pre_field"))

    location_hits = [line for line in text_lines(text) if any(k in line.lower() for k in ["site", "address", "room", "floor", "zone"])]
    test_hits = [line for line in text_lines(text) if "test" in line.lower()]
    deliverable_hits = [line for line in text_lines(text) if any(k in line.lower() for k in ["deliverable", "as-built", "closeout"])]
    access_hits = [line for line in text_lines(text) if any(k in line.lower() for k in ["access", "escort", "badge"])]
    quantity_hits = re.findall(r"\b\d+\s+(?:drops?|aps?|cameras?|racks?|rooms?)\b", text, flags=re.I)
    question_hits = [line for line in text_lines(text) if "?" in line]

    maybe_claim("location_details", location_hits[:20])
    maybe_claim("testing_requirements", test_hits[:20])
    maybe_claim("deliverables_needed", deliverable_hits[:20])
    maybe_claim("access_constraints", access_hits[:20])
    maybe_claim("known_quantities", quantity_hits[:20])
    maybe_claim("open_questions", question_hits[:20])

    if "scope_overview" in allowed_business_fields(post_ref):
        claims.append(_claim(role_id, modality, post_ref, "scope_overview", f"{page_count} drawing pages processed with graph-first placeholder lane.", evidence_refs, "post_hint"))
    if "open_items" in allowed_business_fields(post_ref) and question_hits:
        claims.append(_claim(role_id, modality, post_ref, "open_items", question_hits[:20], evidence_refs, "post_hint"))
    if not text.strip():
        review_flags.append(
            ReviewFlag(
                id=make_id("review"),
                domain_id="professional_services",
                role_id=role_id,
                modality=modality,
                severity="high",
                code="drawing_text_low_confidence",
                message="Drawing packet text extraction produced little or no text; visual review required.",
                evidence_refs=evidence_refs,
                requires_human=True,
                created_at=utc_now(),
            )
        )
    else:
        review_flags.append(
            ReviewFlag(
                id=make_id("review"),
                domain_id="professional_services",
                role_id=role_id,
                modality=modality,
                severity="medium",
                code="drawing_visual_ambiguity",
                message="Drawing packet uses a placeholder visual lane; unresolved spatial ambiguity remains a review item.",
                evidence_refs=evidence_refs,
                requires_human=True,
                created_at=utc_now(),
            )
        )

    role_graph = RoleGraph(
        id=make_id("role_graph"),
        domain_id="professional_services",
        role_id=role_id,
        modality=modality,
        source_artifact_id=path.stem,
        source_ref=source_ref,
        node_refs=[obj.id for obj in evidence if isinstance(obj, DiagramNode)],
        edge_refs=[obj.id for obj in evidence if isinstance(obj, DiagramEdge)],
        evidence_refs=evidence_refs,
        field_claim_refs=[claim.id for claim in claims],
        review_flag_refs=[flag.id for flag in review_flags],
        summary="Drawing packet ingested into page/text/crop scaffolding with graph-first placeholders.",
        confidence=0.52,
        created_at=utc_now(),
    )
    return {"evidence_objects": evidence, "field_claims": claims, "review_flags": review_flags, "role_graph": role_graph}


def ingest_generic_role(role_id: str, path: Path, modality: str) -> dict[str, Any]:
    parsed_artifact = None
    try:
        parsed_artifact = ParserRegistry().parse(path, modality, role_hint=role_id)
    except KeyError:
        parsed_artifact = None
    reason = f"Role {role_id}/{modality} is not implemented for extraction; routed to strict intake_only fallback."
    return _intake_only_from_parsed(role_id, path, modality, parsed_artifact, reason)


def ingest(role_id: str, path: Path, modality: str) -> dict[str, Any]:
    if role_runtime_status(role_id) == "parked":
        raise NotImplementedError(f"Runtime ingestor is parked for role: {role_id}")
    if role_id == "transcript_or_notes":
        return ingest_transcript_or_notes(path, modality)
    return ingest_generic_role(role_id, path, modality)
