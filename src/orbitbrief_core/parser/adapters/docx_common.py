from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


@dataclass(frozen=True, slots=True)
class StructuredDocxBlock:
    block_id: str
    text: str
    role: str
    style_name: str | None
    heading_level: int | None
    list_level: int | None
    table_group_id: str | None
    section_hint: str | None
    confidence: float
    source: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class StructuredDocxHypothesis:
    hypothesis_id: str
    source: str
    blocks: tuple[StructuredDocxBlock, ...]
    confidence: float
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DocxReconciliationResult:
    blocks: tuple[StructuredDocxBlock, ...]
    diagnostics: tuple[str, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)


def _normalize(text: str) -> str:
    return " ".join(str(text or "").split()).strip().lower()


def _has_ooxml_heading_hint(block: StructuredDocxBlock) -> bool:
    style = str(block.style_name or "").lower()
    return "heading" in style or "title" in style


def _looks_like_structural_heading(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    if stripped.endswith((".", "?", "!", ";", ":")):
        return False
    words = stripped.split()
    if len(words) > 8:
        return False
    alpha_tokens = [token for token in words if any(ch.isalpha() for ch in token)]
    if not alpha_tokens:
        return False
    titleish = sum(1 for token in alpha_tokens if token[:1].isupper())
    return (titleish / len(alpha_tokens)) >= 0.65


def build_deterministic_docx_hypothesis(blocks: Sequence[Any]) -> StructuredDocxHypothesis:
    out: list[StructuredDocxBlock] = []
    for index, block in enumerate(blocks):
        role = str(getattr(block, "block_kind", "paragraph"))
        style_name = getattr(block, "style_name", None)
        heading_level = getattr(block, "level", None) if role == "heading" else None
        metadata = dict(getattr(block, "metadata", {}) or {})
        list_level = metadata.get("list_level") if role == "bullet" else None
        table_group_id = None
        if role == "table_row":
            group = metadata.get("table_group_id")
            table_group_id = str(group) if group is not None else "table:ooxml:0000"
        section_hint = metadata.get("section_hint") if isinstance(metadata.get("section_hint"), str) else None
        out.append(
            StructuredDocxBlock(
                block_id=f"docx_ooxml_block:{index:04d}",
                text=str(getattr(block, "text", "")),
                role=role,
                style_name=style_name if isinstance(style_name, str) else None,
                heading_level=heading_level if isinstance(heading_level, int) else None,
                list_level=int(list_level) if isinstance(list_level, int) else None,
                table_group_id=table_group_id,
                section_hint=section_hint,
                confidence=0.82,
                source="ooxml",
                metadata=metadata,
            )
        )
    return StructuredDocxHypothesis(
        hypothesis_id="hypothesis:docx_ooxml",
        source="ooxml",
        blocks=tuple(out),
        confidence=0.82 if out else 0.0,
        metadata={"deterministic": True, "block_count": len(out)},
    )


def reconcile_docx_hypotheses(
    *,
    primary: StructuredDocxHypothesis,
    alternate: StructuredDocxHypothesis | None,
) -> DocxReconciliationResult:
    if alternate is None:
        blocks = tuple(
            StructuredDocxBlock(
                block_id=block.block_id,
                text=block.text,
                role=block.role,
                style_name=block.style_name,
                heading_level=block.heading_level,
                list_level=block.list_level,
                table_group_id=block.table_group_id,
                section_hint=block.section_hint,
                confidence=block.confidence,
                source=block.source,
                metadata={
                    **dict(block.metadata),
                    "winner_source": primary.source,
                    "winner_hypothesis_id": primary.hypothesis_id,
                    "competing_sources": [],
                    "reconciled": False,
                    "reconciliation_reason_codes": [],
                    "disputed": False,
                },
            )
            for block in primary.blocks
        )
        return DocxReconciliationResult(
            blocks=blocks,
            diagnostics=("alternate_docx_hypothesis_unavailable",),
            metadata={"winner_source": primary.source, "winner_hypothesis_id": primary.hypothesis_id},
        )

    alt_lookup = {_normalize(block.text): block for block in alternate.blocks if _normalize(block.text)}
    diagnostics: list[str] = []
    reconciled_blocks: list[StructuredDocxBlock] = []
    competing_sources = tuple(sorted({alternate.source}))

    for block in primary.blocks:
        reasons: list[str] = []
        winner = block
        disputed = False
        alt_block = alt_lookup.get(_normalize(block.text))
        if alt_block is not None:
            # Heading recovery.
            if block.role == "paragraph" and alt_block.role == "heading":
                provider_is_clearly_stronger = alt_block.confidence >= (block.confidence + 0.05)
                allow_heading_override = _has_ooxml_heading_hint(block) or (
                    _looks_like_structural_heading(block.text) and provider_is_clearly_stronger
                )
                if allow_heading_override:
                    winner = StructuredDocxBlock(
                        block_id=block.block_id,
                        text=block.text,
                        role="heading",
                        style_name=block.style_name,
                        heading_level=alt_block.heading_level or 1,
                        list_level=None,
                        table_group_id=block.table_group_id,
                        section_hint=alt_block.section_hint or block.section_hint,
                        confidence=max(block.confidence, alt_block.confidence),
                        source=alt_block.source,
                        metadata=dict(block.metadata),
                    )
                    reasons.append("heading_recovery")
                    disputed = True
            # List nesting recovery.
            if winner.role == "bullet" and alt_block.list_level is not None:
                ooxml_level = winner.list_level
                ooxml_is_ambiguous = ooxml_level is None or ooxml_level <= 1 or bool(winner.metadata.get("list_level_ambiguous"))
                provider_is_stronger = alt_block.confidence >= winner.confidence
                if ooxml_is_ambiguous and alt_block.list_level != (ooxml_level or 1) and provider_is_stronger:
                    winner = StructuredDocxBlock(
                        block_id=winner.block_id,
                        text=winner.text,
                        role=winner.role,
                        style_name=winner.style_name,
                        heading_level=winner.heading_level,
                        list_level=alt_block.list_level,
                        table_group_id=winner.table_group_id,
                        section_hint=winner.section_hint,
                        confidence=max(winner.confidence, alt_block.confidence),
                        source=alt_block.source,
                        metadata=dict(winner.metadata),
                    )
                    reasons.append("list_level_reconciled")
                    disputed = True
            # Table association recovery.
            if winner.role == "table_row" and alt_block.table_group_id and alt_block.table_group_id != winner.table_group_id:
                winner = StructuredDocxBlock(
                    block_id=winner.block_id,
                    text=winner.text,
                    role=winner.role,
                    style_name=winner.style_name,
                    heading_level=winner.heading_level,
                    list_level=winner.list_level,
                    table_group_id=alt_block.table_group_id,
                    section_hint=winner.section_hint,
                    confidence=max(winner.confidence, alt_block.confidence),
                    source=alt_block.source,
                    metadata=dict(winner.metadata),
                )
                reasons.append("table_association_reconciled")
                disputed = True
            # Memo/note section coherence hint.
            if winner.section_hint is None and alt_block.section_hint:
                winner = StructuredDocxBlock(
                    block_id=winner.block_id,
                    text=winner.text,
                    role=winner.role,
                    style_name=winner.style_name,
                    heading_level=winner.heading_level,
                    list_level=winner.list_level,
                    table_group_id=winner.table_group_id,
                    section_hint=alt_block.section_hint,
                    confidence=max(winner.confidence, alt_block.confidence),
                    source=winner.source,
                    metadata=dict(winner.metadata),
                )
                reasons.append("section_hint_reconciled")
        if reasons:
            diagnostics.extend(reasons)
        reconciled_blocks.append(
            StructuredDocxBlock(
                block_id=winner.block_id,
                text=winner.text,
                role=winner.role,
                style_name=winner.style_name,
                heading_level=winner.heading_level,
                list_level=winner.list_level,
                table_group_id=winner.table_group_id,
                section_hint=winner.section_hint,
                confidence=winner.confidence,
                source=winner.source,
                metadata={
                    **dict(winner.metadata),
                    "winner_source": winner.source,
                    "winner_hypothesis_id": alternate.hypothesis_id if winner.source == alternate.source else primary.hypothesis_id,
                    "competing_sources": list(competing_sources),
                    "reconciled": bool(reasons),
                    "reconciliation_reason_codes": list(reasons),
                    "disputed": disputed,
                },
            )
        )

    return DocxReconciliationResult(
        blocks=tuple(reconciled_blocks),
        diagnostics=tuple(diagnostics),
        metadata={
            "winner_source": "mixed",
            "winner_hypothesis_id": f"{primary.hypothesis_id}|{alternate.hypothesis_id}",
            "competing_sources": list(competing_sources),
        },
    )
