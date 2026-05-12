from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from orbitbrief_core.parser.shared.types import (
    ContainerType,
    DiscourseType,
    ReviewCategory,
    ReviewFlag,
    ReviewSeverity,
)


@dataclass(frozen=True, slots=True)
class RouterInput:
    doc_id: str
    filename: str | None = None
    mime_type: str | None = None
    raw_text_preview: str | None = None
    page_count: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RouteEvidence:
    signal_id: str
    signal_type: str
    score: float
    value: str
    source: str
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RouteScore:
    label: str
    score: float
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ParsePlan:
    doc_id: str
    container_type: ContainerType
    discourse_type: DiscourseType
    parser_profile_id: str
    adapter_chain: tuple[str, ...]
    strategy_chain: tuple[str, ...]
    quality_mode: str
    authority_mode: str
    packet_policy: str
    routing_confidence: float
    route_scores: tuple[RouteScore, ...]
    route_evidence: tuple[RouteEvidence, ...]
    review_flags: tuple[ReviewFlag, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


class ParserRouter:
    """Deterministic-first parser route planner."""

    _EMAIL_HEADER_RE = re.compile(r"(?im)^(from|to|cc|subject):\s+")
    _EMAIL_QUOTED_RE = re.compile(r"(?im)^>|\nOn .+ wrote:\n")
    _SPEAKER_LINE_RE = re.compile(r"(?m)^[A-Z][A-Za-z0-9 .'\-]{1,30}:\s")
    _TIMECODE_RE = re.compile(r"\b(?:[01]?\d|2[0-3]):[0-5]\d(?:[:][0-5]\d)?\b")
    _MARKDOWN_HEADER_RE = re.compile(r"(?m)^\s{0,3}#{1,6}\s+\S+")
    _BULLET_RE = re.compile(r"(?m)^\s*[-*]\s+\S+")
    _METADATA_PROLOGUE_RE = re.compile(
        r"(?im)^(customer|service category|project type|business driver|site count|locations|known quantities)\s*[-:]\s+"
    )
    _FORMAL_SECTION_RE = re.compile(
        r"(?im)^(project overview|detailed scope of services|deliverables|assumptions|customer responsibilities|out of scope|risks(?:\s*/\s*dependencies|\s+or\s+dependencies)?|completion criteria|open items)\s*$"
    )
    _NOTE_HEADING_RE = re.compile(
        r"(?im)^\s{0,3}#{1,6}\s*(scope|deliverables|customer responsibilities|assumptions|risks(?:\s*/\s*dependencies|\s+or\s+dependencies)?|open items|open questions|done|out of scope|customer side|risks / deps / access)\s*$"
    )
    _WORKING_NOTES_RE = re.compile(
        r"(?im)(working notes|old note|still seems|maybe keep|need from customer|customer side / needed from them|out / by others|done looks like|still need to confirm|first ask heard was)"
    )
    _CAD_SIGNAL_RE = re.compile(
        r"(?im)\b(floor ?plan|schematic|drawing|title block|sheet(?:\s+no|\s+number)?|revision block|mdf|idf|closet|ap[-_ ]?\d+|rack[-_ ]?\d+|panel[-_ ]?\d+|switch[-_ ]?\d+)\b"
    )

    def __init__(self, compiled_pack: Any) -> None:
        self._compiled_pack = compiled_pack
        self._pack_id = str(getattr(compiled_pack.manifest, "pack_id", "professional_services_text"))
        self._profile_by_modality = self._build_profile_index(compiled_pack)

    def route(self, router_input: RouterInput) -> ParsePlan:
        modality, container_type, stage1_evidence = self._classify_container(router_input)
        route_scores, stage2_evidence = self._score_discourse_profiles(router_input, modality=modality)
        discourse, confidence, profile_scores = self._select_discourse(route_scores)
        if modality in {"cad_sheet", "schematic", "floorplan", "drawing_packet", "site_schematic_pdf", "site_schematic_image"}:
            discourse = DiscourseType.PROJECT_MEMO
            confidence = max(confidence, 0.88)
            profile_scores = (
                RouteScore(label=DiscourseType.PROJECT_MEMO.value, score=round(confidence, 6), reasons=("cad_modality_forced",)),
            )

        parser_profile_id = self._profile_by_modality.get(modality, f"parser:{self._pack_id}:{modality}")
        adapter_chain, strategy_chain, quality_mode, authority_mode, packet_policy = self._synthesize_plan(
            modality=modality,
            discourse_type=discourse,
        )
        flags = self._routing_flags(
            router_input=router_input,
            confidence=confidence,
            route_scores=profile_scores,
            modality=modality,
        )
        return ParsePlan(
            doc_id=router_input.doc_id,
            container_type=container_type,
            discourse_type=discourse,
            parser_profile_id=parser_profile_id,
            adapter_chain=adapter_chain,
            strategy_chain=strategy_chain,
            quality_mode=quality_mode,
            authority_mode=authority_mode,
            packet_policy=packet_policy,
            routing_confidence=confidence,
            route_scores=profile_scores,
            route_evidence=tuple(stage1_evidence + stage2_evidence),
            review_flags=flags,
            metadata={
                "modality": modality,
                "role_id": "drawing_packet" if modality in {"cad_sheet", "schematic", "floorplan", "drawing_packet", "site_schematic_pdf", "site_schematic_image"} else "",
                "pack_id": self._pack_id,
                "profile_available": modality in self._profile_by_modality,
                "template_schema_artifact": bool(router_input.metadata.get("template_schema_artifact")) if isinstance(router_input.metadata, Mapping) else False,
                "template_schema_kind": str(router_input.metadata.get("template_schema_kind", "")) if isinstance(router_input.metadata, Mapping) else "",
                "meta_reference_artifact": bool(router_input.metadata.get("meta_reference_artifact")) if isinstance(router_input.metadata, Mapping) else False,
                "meta_reference_kind": str(router_input.metadata.get("meta_reference_kind", "")) if isinstance(router_input.metadata, Mapping) else "",
                "spreadsheet_block_count": int(router_input.metadata.get("spreadsheet_block_count", 0)) if isinstance(router_input.metadata, Mapping) and isinstance(router_input.metadata.get("spreadsheet_block_count"), int) else 0,
            },
        )

    def _build_profile_index(self, compiled_pack: Any) -> dict[str, str]:
        payload = getattr(compiled_pack, "parser_profiles", None)
        if not isinstance(payload, Mapping):
            return {}
        rows = payload.get("rows")
        if not isinstance(rows, list):
            return {}
        index: dict[str, str] = {}
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            modality = str(row.get("modality", "")).strip()
            profile_id = str(row.get("parser_profile_id", "")).strip()
            if modality and profile_id:
                index[modality] = profile_id
        return index

    def _classify_container(self, router_input: RouterInput) -> tuple[str, ContainerType, list[RouteEvidence]]:
        evidence: list[RouteEvidence] = []
        filename = (router_input.filename or "").strip()
        suffix = Path(filename).suffix.lower() if filename else ""
        mime = (router_input.mime_type or "").lower()
        text = router_input.raw_text_preview or ""
        meta = dict(router_input.metadata)

        def add(signal_id: str, signal_type: str, score: float, value: str, source: str, details: Mapping[str, Any] | None = None) -> None:
            evidence.append(
                RouteEvidence(
                    signal_id=signal_id,
                    signal_type=signal_type,
                    score=score,
                    value=value,
                    source=source,
                    details=details or {},
                )
            )

        if suffix == ".docx" or "wordprocessingml.document" in mime:
            add("ext_docx", "file_extension", 1.0, "docx", "filename/mime")
            return "docx", ContainerType.DOCUMENT, evidence
        if suffix in {".xlsx", ".csv"} or "spreadsheetml" in mime or "csv" in mime:
            modality = "xlsx" if suffix == ".xlsx" or "spreadsheetml" in mime else "csv"
            add("ext_spreadsheet", "file_extension", 0.98, modality, "filename/mime")
            return modality, ContainerType.DOCUMENT, evidence
        if suffix == ".md" or "markdown" in mime or self._MARKDOWN_HEADER_RE.search(text):
            add("ext_md", "file_extension", 0.95, "md", "filename/mime/content")
            return "md", ContainerType.DOCUMENT, evidence
        if suffix in {".eml", ".msg"} or self._EMAIL_HEADER_RE.search(text):
            add("email_header", "content_probe", 0.95, "email_export", "filename/content")
            return "email_export", ContainerType.EMAIL, evidence
        site_schematic_hint = bool(meta.get("drawing_packet")) or bool(meta.get("site_schematic")) or bool(meta.get("site_schematic_hint"))
        cad_meta_hint = bool(meta.get("cad_hint"))
        cad_text_hint = bool(self._CAD_SIGNAL_RE.search(text))
        cad_name_hint = any(token in filename.lower() for token in ("floorplan", "schematic", "drawing", "sheet", "layout")) if filename else False
        if suffix == ".pdf" or "application/pdf" in mime:
            if site_schematic_hint:
                add(
                    "site_schematic_pdf_lane",
                    "pdf_mode",
                    0.93,
                    "site_schematic_pdf",
                    "metadata",
                    {"site_schematic_hint": site_schematic_hint},
                )
                return "site_schematic_pdf", ContainerType.PDF, evidence
            if cad_meta_hint or cad_text_hint or cad_name_hint:
                add(
                    "cad_pdf_lane",
                    "pdf_mode",
                    0.92,
                    "cad_sheet",
                    "filename/content/metadata",
                    {"cad_meta_hint": cad_meta_hint, "cad_text_hint": cad_text_hint, "cad_name_hint": cad_name_hint, "site_schematic_hint": site_schematic_hint},
                )
                return "cad_sheet", ContainerType.PDF, evidence
            native_ratio = float(meta.get("native_text_ratio", 1.0)) if isinstance(meta.get("native_text_ratio"), (int, float)) else 1.0
            ocr_conf = float(meta.get("ocr_confidence", 1.0)) if isinstance(meta.get("ocr_confidence"), (int, float)) else 1.0
            if native_ratio < 0.2 or ocr_conf < 0.55:
                add("pdf_ocr_mode", "pdf_mode", 0.9, "pdf_ocr", "metadata", {"native_text_ratio": native_ratio, "ocr_confidence": ocr_conf})
                return "pdf_ocr", ContainerType.PDF, evidence
            add("pdf_text_mode", "pdf_mode", 0.9, "pdf_text", "metadata", {"native_text_ratio": native_ratio, "ocr_confidence": ocr_conf})
            return "pdf_text", ContainerType.PDF, evidence
        if suffix in {".png", ".jpg", ".jpeg", ".webp"} or mime.startswith("image/"):
            if bool(meta.get("site_schematic")) or bool(meta.get("site_schematic_hint")):
                add("site_schematic_image_lane", "upload_metadata", 0.9, "site_schematic_image", "metadata")
                return "site_schematic_image", ContainerType.DOCUMENT, evidence
            if "schematic" in filename.lower() if filename else False:
                add("cad_schematic_lane", "file_extension", 0.9, "schematic", "filename/mime")
                return "schematic", ContainerType.DOCUMENT, evidence
            if cad_meta_hint and bool(meta.get("drawing_packet")):
                add("cad_drawing_packet_lane", "upload_metadata", 0.88, "drawing_packet", "metadata")
                return "drawing_packet", ContainerType.DOCUMENT, evidence
            add("cad_floorplan_lane", "file_extension", 0.86, "floorplan", "filename/mime")
            return "floorplan", ContainerType.DOCUMENT, evidence
        if meta.get("upload_source") in {"clipboard", "pasted"} and not filename:
            add("pasted_source", "upload_metadata", 0.85, "pasted_notes", "metadata")
            return "pasted_notes", ContainerType.NOTES, evidence
        if suffix == ".txt":
            add("ext_txt", "file_extension", 0.9, "txt", "filename")
            return "txt", ContainerType.TEXT, evidence
        add("fallback_txt", "fallback", 0.6, "txt", "default")
        return "txt", ContainerType.TEXT, evidence

    def _score_discourse_profiles(self, router_input: RouterInput, *, modality: str) -> tuple[dict[DiscourseType, float], list[RouteEvidence]]:
        text = router_input.raw_text_preview or ""
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        scores: dict[DiscourseType, float] = {
            DiscourseType.CALL_TRANSCRIPT: 0.0,
            DiscourseType.MEETING_NOTES: 0.0,
            DiscourseType.EMAIL_THREAD: 0.0,
            DiscourseType.PROJECT_MEMO: 0.0,
            DiscourseType.HYBRID_NOTES_MEMO: 0.0,
        }
        evidence: list[RouteEvidence] = []

        speaker_hits = len(self._SPEAKER_LINE_RE.findall(text))
        timecode_hits = len(self._TIMECODE_RE.findall(text))
        bullet_hits = len(self._BULLET_RE.findall(text))
        header_hits = len(self._MARKDOWN_HEADER_RE.findall(text))
        email_headers = len(self._EMAIL_HEADER_RE.findall(text))
        email_quotes = len(self._EMAIL_QUOTED_RE.findall(text))
        memo_heading_hits = sum(text.lower().count(token) for token in (
            "scope",
            "assumptions",
            "deliverables",
            "exclusions",
            "out of scope",
            "schedule",
            "responsibilities",
            "risks",
            "dependencies",
            "open items",
        ))
        formal_section_hits = sum(1 for line in lines if self._FORMAL_SECTION_RE.match(line))
        metadata_prologue_hits = sum(1 for line in lines if self._METADATA_PROLOGUE_RE.match(line))
        note_heading_hits = sum(1 for line in lines if self._NOTE_HEADING_RE.match(line))
        working_note_hits = len(self._WORKING_NOTES_RE.findall(text))
        question_prompt_hits = len(re.findall(r"(?im)^(confirm|clarify|pending|still need to confirm|open items?)\b", text))
        spreadsheet_sheet_hits = len(re.findall(r"(?im)^sheet:\s+", text))
        spreadsheet_kv_hits = len(re.findall(r"(?m)^[^:\n]{2,48}:\s+.+$", text))
        spreadsheet_row_hits = len(re.findall(r";", text))
        formal_memo_signal_count = int(formal_section_hits > 0) + int(metadata_prologue_hits > 0) + int(memo_heading_hits >= 5)
        notes_signal_count = int(bullet_hits > 0) + int(note_heading_hits > 0) + int(working_note_hits > 0)

        def boost(profile: DiscourseType, amount: float, sid: str, sval: str, src: str) -> None:
            scores[profile] += amount
            evidence.append(RouteEvidence(signal_id=sid, signal_type="discourse_signal", score=amount, value=sval, source=src))

        if speaker_hits:
            boost(DiscourseType.CALL_TRANSCRIPT, min(0.5, speaker_hits * 0.06), "speaker_label_density", str(speaker_hits), "content")
        if timecode_hits:
            boost(DiscourseType.CALL_TRANSCRIPT, min(0.35, timecode_hits * 0.05), "timecode_hits", str(timecode_hits), "content")
        if bullet_hits:
            boost(DiscourseType.MEETING_NOTES, min(0.4, bullet_hits * 0.04), "bullet_density", str(bullet_hits), "content")
        if header_hits:
            boost(DiscourseType.PROJECT_MEMO, min(0.2, header_hits * 0.03), "heading_density", str(header_hits), "content")
        if memo_heading_hits:
            boost(DiscourseType.PROJECT_MEMO, min(0.45, memo_heading_hits * 0.04), "memo_heading_priors", str(memo_heading_hits), "content")
        if formal_section_hits:
            boost(DiscourseType.PROJECT_MEMO, min(0.9, formal_section_hits * 0.14), "formal_sections", str(formal_section_hits), "content")
        if metadata_prologue_hits:
            boost(DiscourseType.PROJECT_MEMO, min(0.8, metadata_prologue_hits * 0.12), "metadata_prologue", str(metadata_prologue_hits), "content")
        if note_heading_hits:
            boost(DiscourseType.MEETING_NOTES, min(0.5, note_heading_hits * 0.07), "note_headings", str(note_heading_hits), "content")
        if working_note_hits:
            boost(DiscourseType.MEETING_NOTES, min(0.3, working_note_hits * 0.08), "working_note_markers", str(working_note_hits), "content")
            boost(DiscourseType.HYBRID_NOTES_MEMO, min(0.5, working_note_hits * 0.11), "hybrid_working_note_markers", str(working_note_hits), "content")
        if question_prompt_hits:
            boost(DiscourseType.MEETING_NOTES, min(0.2, question_prompt_hits * 0.04), "question_prompts", str(question_prompt_hits), "content")

        if modality in {"xlsx", "csv"}:
            if spreadsheet_sheet_hits:
                boost(DiscourseType.PROJECT_MEMO, min(0.55, spreadsheet_sheet_hits * 0.18), "spreadsheet_sheet_markers", str(spreadsheet_sheet_hits), "content")
            if spreadsheet_kv_hits:
                boost(DiscourseType.PROJECT_MEMO, min(0.55, spreadsheet_kv_hits * 0.035), "spreadsheet_kv_rows", str(spreadsheet_kv_hits), "content")
            if spreadsheet_row_hits:
                boost(DiscourseType.HYBRID_NOTES_MEMO, min(0.28, spreadsheet_row_hits * 0.01), "spreadsheet_row_density", str(spreadsheet_row_hits), "content")
            if any(token in text.lower() for token in ("qty of sites", "project duration", "billing type", "job description", "site:", "unit sell quantity")):
                boost(DiscourseType.PROJECT_MEMO, 0.28, "spreadsheet_managed_services_markers", modality, "content")

        if email_headers:
            boost(DiscourseType.EMAIL_THREAD, min(0.6, email_headers * 0.12), "email_headers", str(email_headers), "content")
        if email_quotes:
            boost(DiscourseType.EMAIL_THREAD, min(0.3, email_quotes * 0.05), "email_quote_markers", str(email_quotes), "content")

        if note_heading_hits and bullet_hits and not formal_memo_signal_count:
            boost(DiscourseType.MEETING_NOTES, 0.18, "markdown_notes_structure", str(note_heading_hits), "content")

        if formal_memo_signal_count and notes_signal_count >= 2 and working_note_hits:
            boost(DiscourseType.HYBRID_NOTES_MEMO, 0.55, "mixed_format_signals", f"memo={formal_memo_signal_count};notes={notes_signal_count}", "content")
        elif working_note_hits and note_heading_hits and memo_heading_hits >= 4:
            boost(DiscourseType.HYBRID_NOTES_MEMO, 0.42, "working_notes_with_sections", str(working_note_hits), "content")
        elif working_note_hits and note_heading_hits >= 4 and any(token in text.lower() for token in ("old note", "not final", "still seems in", "done looks like", "out / by others")):
            boost(DiscourseType.HYBRID_NOTES_MEMO, 0.34, "working_notes_dense_sections", str(note_heading_hits), "content")

        # Modality-sensitive priors: markdown docs are more likely note-oriented unless
        # strong formal memo markers are present.
        if modality == "md" and formal_memo_signal_count == 0:
            scores[DiscourseType.MEETING_NOTES] += 0.08
            scores[DiscourseType.PROJECT_MEMO] = max(0.0, scores[DiscourseType.PROJECT_MEMO] - 0.05)

        # Slight base priors prevent pathological zero-score ties.
        scores[DiscourseType.MEETING_NOTES] += 0.05
        scores[DiscourseType.PROJECT_MEMO] += 0.05
        scores[DiscourseType.HYBRID_NOTES_MEMO] += 0.03
        return scores, evidence

    def _select_discourse(self, scores: Mapping[DiscourseType, float]) -> tuple[DiscourseType, float, tuple[RouteScore, ...]]:
        ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        top_profile, top_score = ordered[0]
        second_score = ordered[1][1] if len(ordered) > 1 else 0.0

        # Prefer hybrid when the document looks like a working-notes memo blend,
        # not only when scores are nearly tied.
        if top_profile is not DiscourseType.HYBRID_NOTES_MEMO:
            hybrid_score = scores[DiscourseType.HYBRID_NOTES_MEMO]
            memo_score = scores[DiscourseType.PROJECT_MEMO]
            if hybrid_score >= 0.45 and (top_score - hybrid_score) <= 0.05:
                top_profile = DiscourseType.HYBRID_NOTES_MEMO
                top_score = hybrid_score
            elif top_profile is DiscourseType.MEETING_NOTES and hybrid_score >= 0.9 and memo_score >= 0.3 and (top_score - hybrid_score) <= 0.25:
                top_profile = DiscourseType.HYBRID_NOTES_MEMO
                top_score = hybrid_score

        total = sum(max(value, 0.0) for value in scores.values()) or 1.0
        confidence = max(0.0, min(1.0, top_score / total + (top_score - second_score)))
        route_scores = tuple(
            RouteScore(
                label=profile.value,
                score=round(score, 6),
                reasons=(),
            )
            for profile, score in sorted(scores.items(), key=lambda item: item[1], reverse=True)
        )
        return top_profile, confidence, route_scores

    def _synthesize_plan(
        self,
        *,
        modality: str,
        discourse_type: DiscourseType,
    ) -> tuple[tuple[str, ...], tuple[str, ...], str, str, str]:
        adapter_chain = (modality,)
        strategy_map: dict[DiscourseType, tuple[str, ...]] = {
            DiscourseType.CALL_TRANSCRIPT: ("call_transcript",),
            DiscourseType.MEETING_NOTES: ("meeting_notes",),
            DiscourseType.EMAIL_THREAD: ("email_thread",),
            DiscourseType.PROJECT_MEMO: ("project_memo",),
            DiscourseType.HYBRID_NOTES_MEMO: ("hybrid", "project_memo"),
        }
        authority_map: dict[DiscourseType, str] = {
            DiscourseType.CALL_TRANSCRIPT: "speaker_turn_weighted",
            DiscourseType.MEETING_NOTES: "notes_context_weighted",
            DiscourseType.EMAIL_THREAD: "current_message_priority",
            DiscourseType.PROJECT_MEMO: "authored_section_weighted",
            DiscourseType.HYBRID_NOTES_MEMO: "zone_sensitive",
        }
        packet_policy_map: dict[DiscourseType, str] = {
            DiscourseType.CALL_TRANSCRIPT: "episode_packets",
            DiscourseType.MEETING_NOTES: "action_cluster_packets",
            DiscourseType.EMAIL_THREAD: "message_delta_packets",
            DiscourseType.PROJECT_MEMO: "section_packets",
            DiscourseType.HYBRID_NOTES_MEMO: "zone_packets",
        }
        quality_mode = "ocr_hardened" if modality == "pdf_ocr" else "standard"
        if modality in {"cad_sheet", "schematic", "floorplan", "drawing_packet", "site_schematic_pdf", "site_schematic_image"}:
            return (
                adapter_chain,
                ("site_package",),
                "cad_hardened",
                "diagram_weighted",
                "drawing_packets",
            )
        if modality in {"xlsx", "csv"}:
            return (
                adapter_chain,
                ("spreadsheet_roster",),
                "tabular_hardened",
                "structured_tabular",
                "row_cluster_packets",
            )
        return (
            adapter_chain,
            strategy_map[discourse_type],
            quality_mode,
            authority_map[discourse_type],
            packet_policy_map[discourse_type],
        )

    def _routing_flags(
        self,
        *,
        router_input: RouterInput,
        confidence: float,
        route_scores: tuple[RouteScore, ...],
        modality: str,
    ) -> tuple[ReviewFlag, ...]:
        flags: list[ReviewFlag] = []

        def add(code: str, message: str, severity: ReviewSeverity, category: ReviewCategory, details: Mapping[str, Any] | None = None) -> None:
            flags.append(
                ReviewFlag(
                    flag_id=f"route:{router_input.doc_id}:{code}",
                    severity=severity,
                    category=category,
                    message=message,
                    metadata=details or {},
                )
            )

        if isinstance(router_input.metadata, Mapping) and bool(router_input.metadata.get("template_schema_artifact")):
            add(
                "template_schema_artifact",
                "Artifact looks like a prompt package or JSON schema template and should be treated conservatively.",
                ReviewSeverity.WARNING,
                ReviewCategory.BOUNDARY_RISK,
                {"template_schema_kind": router_input.metadata.get("template_schema_kind")},
            )

        if isinstance(router_input.metadata, Mapping) and bool(router_input.metadata.get("meta_reference_artifact")):
            add(
                "meta_reference_artifact",
                "Artifact looks like an internal architecture or parser reference document and should not emit business claims.",
                ReviewSeverity.WARNING,
                ReviewCategory.BOUNDARY_RISK,
                {"meta_reference_kind": router_input.metadata.get("meta_reference_kind")},
            )

        if confidence < 0.45:
            add(
                "low_confidence",
                "Router confidence is low; downstream parser should be review-first.",
                ReviewSeverity.WARNING,
                ReviewCategory.AMBIGUITY,
                {"routing_confidence": confidence},
            )
        if len(route_scores) >= 2:
            gap = route_scores[0].score - route_scores[1].score
            if gap <= 0.10:
                add(
                    "ambiguous_route",
                    "Top discourse routes are close; selected route may be ambiguous.",
                    ReviewSeverity.WARNING,
                    ReviewCategory.AMBIGUITY,
                    {
                        "top_label": route_scores[0].label,
                        "runner_up_label": route_scores[1].label,
                        "score_gap": gap,
                    },
                )
        if modality == "pdf_ocr":
            add(
                "ocr_route",
                "PDF routed through OCR-sensitive lane; extraction quality may vary.",
                ReviewSeverity.INFO,
                ReviewCategory.QUALITY,
            )
        return tuple(flags)
