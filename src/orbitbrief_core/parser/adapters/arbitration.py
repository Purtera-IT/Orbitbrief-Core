from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


@dataclass(frozen=True, slots=True)
class PageArbitrationResult:
    selected_blocks: tuple[Any, ...]
    selected_tables: tuple[Any, ...]
    hypothesis_scores: Mapping[str, float]
    repeated_header_texts: tuple[str, ...] = ()
    repeated_footer_texts: tuple[str, ...] = ()
    disagreements: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


def _normalize_text(text: str) -> str:
    return " ".join(str(text or "").replace("\x00", " ").split()).strip()


def _key_for_block(block: Any) -> str:
    text = _normalize_text(getattr(block, "text", ""))
    return text[:180].lower()


def _repeated_margin_texts(blocks: Sequence[Any], *, margin_threshold: float = 120.0) -> tuple[tuple[str, ...], tuple[str, ...]]:
    headers: dict[str, set[int]] = {}
    footers: dict[str, set[int]] = {}
    pages = {int(getattr(block, "page_index", 0)) for block in blocks}
    if not pages:
        return (), ()
    for block in blocks:
        bbox = getattr(block, "bbox", None)
        if not isinstance(bbox, tuple) or len(bbox) != 4:
            continue
        _, y0, _, y1 = bbox
        text = _normalize_text(getattr(block, "text", "")).lower()
        if not text or len(text) > 120:
            continue
        page_index = int(getattr(block, "page_index", 0))
        if y0 <= margin_threshold:
            headers.setdefault(text, set()).add(page_index)
        if y1 >= 700.0:
            footers.setdefault(text, set()).add(page_index)
    page_threshold = max(2, math.ceil(len(pages) * 0.6))
    repeated_headers = tuple(sorted(text for text, page_ids in headers.items() if len(page_ids) >= page_threshold))
    repeated_footers = tuple(sorted(text for text, page_ids in footers.items() if len(page_ids) >= page_threshold))
    return repeated_headers, repeated_footers


def _score_hypothesis(hypothesis: Any) -> float:
    blocks = tuple(getattr(hypothesis, "page_blocks", ()))
    tables = tuple(getattr(hypothesis, "table_regions", ()))
    text_chars = sum(len(getattr(block, "text", "")) for block in blocks)
    block_count = len(blocks)
    heading_bonus = sum(1 for block in blocks if getattr(block, "role", "") == "heading") * 2.0
    table_bonus = len(tables) * 1.5
    page_coverage_bonus = len({int(getattr(block, "page_index", 0)) for block in blocks}) * 2.0
    structure_bonus = 0.0
    source = str(getattr(hypothesis, "source", "")).lower()
    metadata = getattr(hypothesis, "metadata", {}) or {}
    if source == "docling":
        structure_bonus += 12.0 if not bool(metadata.get("degraded", False)) else -5.0
    if source == "mineru":
        structure_bonus += 10.0 if not bool(metadata.get("degraded", False)) else -4.0
    if source == "paddleocr_vl":
        structure_bonus += 11.0 if not bool(metadata.get("degraded", False)) else -3.0
    if source == "pp_structure":
        structure_bonus += 7.0 if not bool(metadata.get("degraded", False)) else -2.0
    if source == "tesseract":
        structure_bonus -= 3.0
    confidence = float(getattr(hypothesis, "confidence", 0.0))
    ocr_conf_values = [
        float(getattr(block, "metadata", {}).get("ocr_confidence", getattr(block, "confidence", 0.0)))
        for block in blocks
        if isinstance(getattr(block, "metadata", {}), Mapping)
    ]
    ocr_confidence = (sum(ocr_conf_values) / len(ocr_conf_values)) if ocr_conf_values else confidence
    noisy_penalty = 0.0
    weak_blocks = 0
    for block in blocks:
        text = _normalize_text(getattr(block, "text", ""))
        if text and len(text) >= 6:
            alpha = sum(1 for ch in text if ch.isalpha())
            ratio = alpha / max(1, len(text))
            if ratio < 0.38:
                noisy_penalty += 1.0
        block_conf = float(getattr(block, "confidence", 0.0))
        if block_conf < 0.45:
            weak_blocks += 1
    structure_bonus += min(8.0, ocr_confidence * 8.0)
    structure_bonus -= min(10.0, noisy_penalty + weak_blocks * 0.6)
    return (
        confidence * 100.0
        + min(200.0, text_chars / 12.0)
        + min(40.0, block_count * 1.2)
        + heading_bonus
        + table_bonus
        + page_coverage_bonus
        + structure_bonus
    )


def _detect_reading_order_dispute(hypotheses: Sequence[Any]) -> tuple[bool, str | None]:
    if len(hypotheses) < 2:
        return False, None
    ranked = sorted(hypotheses, key=_score_hypothesis, reverse=True)[:2]
    first = ranked[0]
    second = ranked[1]
    first_seq = [_key_for_block(block) for block in getattr(first, "page_blocks", ()) if _key_for_block(block)]
    second_seq = [_key_for_block(block) for block in getattr(second, "page_blocks", ()) if _key_for_block(block)]
    window = min(6, len(first_seq), len(second_seq))
    if window >= 2 and first_seq[:window] != second_seq[:window]:
        return True, f"reading_order_dispute:{getattr(first, 'source', 'a')}:{getattr(second, 'source', 'b')}"
    return False, None


def _detect_heading_body_disputes(hypotheses: Sequence[Any]) -> tuple[bool, list[str], bool]:
    role_by_key: dict[str, set[str]] = {}
    table_like_by_key: dict[str, set[str]] = {}
    for hypothesis in hypotheses:
        source = str(getattr(hypothesis, "source", "unknown"))
        for block in getattr(hypothesis, "page_blocks", ()):
            key = _key_for_block(block)
            if not key:
                continue
            role = str(getattr(block, "role", "paragraph"))
            role_by_key.setdefault(key, set()).add(role)
            if role in {"table", "paragraph"}:
                table_like_by_key.setdefault(key, set()).add(f"{source}:{role}")
    disagreements: list[str] = []
    heading_body = False
    section_boundary = False
    for key, roles in role_by_key.items():
        if "heading" in roles and "paragraph" in roles:
            heading_body = True
            section_boundary = True
            disagreements.append(f"heading_body_dispute:{key[:60]}")
    table_attachment = any(
        len(tags) > 1 and "|" in key
        for key, tags in table_like_by_key.items()
    )
    if table_attachment:
        disagreements.append("table_paragraph_attachment_dispute")
    return heading_body, disagreements, section_boundary


def _annotate_selected_blocks(
    blocks: tuple[Any, ...],
    *,
    winner_hypothesis_id: str,
    winner_source: str,
    competing_sources: tuple[str, ...],
    reason_codes: tuple[str, ...],
    disputed: bool,
) -> tuple[Any, ...]:
    annotated: list[Any] = []
    for block in blocks:
        existing = dict(getattr(block, "metadata", {}) or {})
        merged = {
            **existing,
            "winner_hypothesis_id": winner_hypothesis_id,
            "winner_source": winner_source,
            "competing_sources": list(competing_sources),
            "arbitration_reason_codes": list(reason_codes),
            "disputed": disputed,
            "arbitration_score": float(getattr(block, "confidence", 0.0)),
        }
        annotated.append(
            block.__class__(
                block_id=getattr(block, "block_id"),
                page_index=int(getattr(block, "page_index", 0)),
                bbox=getattr(block, "bbox", None),
                text=getattr(block, "text", ""),
                role=getattr(block, "role", "paragraph"),
                confidence=float(getattr(block, "confidence", 0.0)),
                source=getattr(block, "source", winner_source),
                metadata=merged,
            )
        )
    return tuple(annotated)


def arbitrate_hypotheses(hypotheses: Sequence[Any]) -> PageArbitrationResult:
    if not hypotheses:
        return PageArbitrationResult(selected_blocks=(), selected_tables=(), hypothesis_scores={}, disagreements=("no_hypotheses",))

    scores: dict[str, float] = {}
    for hypothesis in hypotheses:
        scores[str(getattr(hypothesis, "hypothesis_id", "unknown"))] = round(_score_hypothesis(hypothesis), 6)
    ranked = sorted(hypotheses, key=_score_hypothesis, reverse=True)
    winner = ranked[0]
    winner_hypothesis_id = str(getattr(winner, "hypothesis_id", "unknown"))
    winner_source = str(getattr(winner, "source", "unknown"))
    competing_sources = tuple(sorted({str(getattr(h, "source", "unknown")) for h in hypotheses if h is not winner}))

    reason_codes: list[str] = []
    disagreements: list[str] = []

    reading_dispute, reading_reason = _detect_reading_order_dispute(hypotheses)
    if reading_dispute and reading_reason is not None:
        reason_codes.append("reading_order_dispute")
        disagreements.append(reading_reason)
    heading_body, heading_disagreements, section_boundary = _detect_heading_body_disputes(hypotheses)
    if heading_body:
        reason_codes.append("heading_body_dispute")
    if section_boundary:
        reason_codes.append("section_boundary_dispute")
    disagreements.extend(heading_disagreements)
    if "table_paragraph_attachment_dispute" in heading_disagreements:
        reason_codes.append("table_attachment_dispute")

    if len(ranked) > 1:
        lead = scores[str(getattr(ranked[0], "hypothesis_id", "unknown"))]
        runner = scores[str(getattr(ranked[1], "hypothesis_id", "unknown"))]
        if abs(lead - runner) <= 12.0:
            reason_codes.append("close_hypothesis_scores")
            disagreements.append(f"close_pdf_hypotheses:{getattr(ranked[0], 'source', 'a')}:{getattr(ranked[1], 'source', 'b')}")
            reason_codes.append("reading_order_uncertain")

    repeated_headers, repeated_footers = _repeated_margin_texts(tuple(getattr(winner, "page_blocks", ())))
    filtered_blocks = tuple(
        block
        for block in tuple(getattr(winner, "page_blocks", ()))
        if _normalize_text(getattr(block, "text", "")).lower() not in set(repeated_headers + repeated_footers)
    )
    disputed = len(reason_codes) > 0
    winner_blocks = tuple(getattr(winner, "page_blocks", ()))
    if winner_blocks:
        avg_conf = sum(float(getattr(block, "confidence", 0.0)) for block in winner_blocks) / len(winner_blocks)
        if avg_conf < 0.55:
            reason_codes.append("low_confidence_ocr")
        weak_ocr_blocks = sum(1 for block in winner_blocks if float(getattr(block, "confidence", 0.0)) < 0.45)
        if weak_ocr_blocks >= max(2, int(len(winner_blocks) * 0.35)):
            reason_codes.append("weak_ocr")
    disputed = len(reason_codes) > 0
    annotated_blocks = _annotate_selected_blocks(
        filtered_blocks,
        winner_hypothesis_id=winner_hypothesis_id,
        winner_source=winner_source,
        competing_sources=competing_sources,
        reason_codes=tuple(sorted(set(reason_codes))),
        disputed=disputed,
    )
    return PageArbitrationResult(
        selected_blocks=annotated_blocks,
        selected_tables=tuple(getattr(winner, "table_regions", ())),
        hypothesis_scores=scores,
        repeated_header_texts=repeated_headers,
        repeated_footer_texts=repeated_footers,
        disagreements=tuple(sorted(set(disagreements))),
        metadata={
            "winner": winner_source,
            "winner_hypothesis_id": winner_hypothesis_id,
            "competing_sources": list(competing_sources),
            "arbitration_reason_codes": tuple(sorted(set(reason_codes))),
            "disputed": disputed,
            "reading_order_uncertain": "reading_order_uncertain" in reason_codes,
        },
    )
