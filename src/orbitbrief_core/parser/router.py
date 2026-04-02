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

    def __init__(self, compiled_pack: Any) -> None:
        self._compiled_pack = compiled_pack
        self._pack_id = str(getattr(compiled_pack.manifest, "pack_id", "professional_services_text"))
        self._profile_by_modality = self._build_profile_index(compiled_pack)

    def route(self, router_input: RouterInput) -> ParsePlan:
        modality, container_type, stage1_evidence = self._classify_container(router_input)
        route_scores, stage2_evidence = self._score_discourse_profiles(router_input)
        discourse, confidence, profile_scores = self._select_discourse(route_scores)

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
                "pack_id": self._pack_id,
                "profile_available": modality in self._profile_by_modality,
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
        if suffix == ".md" or "markdown" in mime or self._MARKDOWN_HEADER_RE.search(text):
            add("ext_md", "file_extension", 0.95, "md", "filename/mime/content")
            return "md", ContainerType.DOCUMENT, evidence
        if suffix in {".eml", ".msg"} or self._EMAIL_HEADER_RE.search(text):
            add("email_header", "content_probe", 0.95, "email_export", "filename/content")
            return "email_export", ContainerType.EMAIL, evidence
        if suffix == ".pdf" or "application/pdf" in mime:
            native_ratio = float(meta.get("native_text_ratio", 1.0)) if isinstance(meta.get("native_text_ratio"), (int, float)) else 1.0
            ocr_conf = float(meta.get("ocr_confidence", 1.0)) if isinstance(meta.get("ocr_confidence"), (int, float)) else 1.0
            if native_ratio < 0.2 or ocr_conf < 0.55:
                add("pdf_ocr_mode", "pdf_mode", 0.9, "pdf_ocr", "metadata", {"native_text_ratio": native_ratio, "ocr_confidence": ocr_conf})
                return "pdf_ocr", ContainerType.PDF, evidence
            add("pdf_text_mode", "pdf_mode", 0.9, "pdf_text", "metadata", {"native_text_ratio": native_ratio, "ocr_confidence": ocr_conf})
            return "pdf_text", ContainerType.PDF, evidence
        if meta.get("upload_source") in {"clipboard", "pasted"} and not filename:
            add("pasted_source", "upload_metadata", 0.85, "pasted_notes", "metadata")
            return "pasted_notes", ContainerType.NOTES, evidence
        if suffix == ".txt":
            add("ext_txt", "file_extension", 0.9, "txt", "filename")
            return "txt", ContainerType.TEXT, evidence
        add("fallback_txt", "fallback", 0.6, "txt", "default")
        return "txt", ContainerType.TEXT, evidence

    def _score_discourse_profiles(self, router_input: RouterInput) -> tuple[dict[DiscourseType, float], list[RouteEvidence]]:
        text = router_input.raw_text_preview or ""
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
        memo_heading_hits = sum(text.lower().count(token) for token in ("scope", "assumptions", "deliverables", "exclusions", "schedule", "responsibilities"))

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
            boost(DiscourseType.PROJECT_MEMO, min(0.35, header_hits * 0.05), "heading_density", str(header_hits), "content")
        if memo_heading_hits:
            boost(DiscourseType.PROJECT_MEMO, min(0.4, memo_heading_hits * 0.05), "memo_heading_priors", str(memo_heading_hits), "content")
        if email_headers:
            boost(DiscourseType.EMAIL_THREAD, min(0.6, email_headers * 0.12), "email_headers", str(email_headers), "content")
        if email_quotes:
            boost(DiscourseType.EMAIL_THREAD, min(0.3, email_quotes * 0.05), "email_quote_markers", str(email_quotes), "content")

        mixed_note_signals = 0
        if bullet_hits > 0:
            mixed_note_signals += 1
        if header_hits > 0:
            mixed_note_signals += 1
        if email_headers > 0:
            mixed_note_signals += 1
        if mixed_note_signals >= 2:
            boost(DiscourseType.HYBRID_NOTES_MEMO, 0.55, "mixed_format_signals", str(mixed_note_signals), "content")

        # Slight base priors prevent pathological zero-score ties.
        scores[DiscourseType.MEETING_NOTES] += 0.05
        scores[DiscourseType.PROJECT_MEMO] += 0.05
        scores[DiscourseType.HYBRID_NOTES_MEMO] += 0.03
        return scores, evidence

    def _select_discourse(self, scores: Mapping[DiscourseType, float]) -> tuple[DiscourseType, float, tuple[RouteScore, ...]]:
        ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        top_profile, top_score = ordered[0]
        second_score = ordered[1][1] if len(ordered) > 1 else 0.0

        # Prefer hybrid when a mixed candidate is close enough.
        if top_profile is not DiscourseType.HYBRID_NOTES_MEMO:
            hybrid_score = scores[DiscourseType.HYBRID_NOTES_MEMO]
            if hybrid_score > 0.0 and (top_score - hybrid_score) <= 0.08:
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

