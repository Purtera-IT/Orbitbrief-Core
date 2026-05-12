from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
import tempfile
from typing import Any, Mapping

from orbitbrief_core.parser.adapters.common import extract_bytes, extract_path
from orbitbrief_core.parser.adapters.providers.base import ProviderPdfHypothesis
from orbitbrief_core.parser.adapters.providers.docling_provider import extract_docling_pdf_hypothesis
from orbitbrief_core.parser.adapters.providers.pp_structure_provider import extract_pp_structure_image_hypothesis
from orbitbrief_core.parser.router import RouterInput
from orbitbrief_core.parser.site_schematic.models import (
    SiteSchematicLayoutBlockObservation,
    SiteSchematicPageObservation,
    SiteSchematicTableCellObservation,
    SiteSchematicTableObservation,
    SiteSchematicVectorObservation,
    SiteSchematicWordObservation,
)

_AGGRESSIVE_DOCILING_SHEETS = {"notes_spec", "legend_symbol", "schedule_sheet"}
_CONSERVATIVE_DOCILING_SHEETS = {
    "floorplan_overall",
    "floorplan_detail",
    "equipment_room_layout",
    "installation_detail",
    "rack_detail",
    "riser_diagram",
}
_MIXED_DETAIL_SHEETS = {"floorplan_detail", "equipment_room_layout", "installation_detail", "rack_detail"}
_LIGHTWEIGHT_LAYOUT_SHEETS = {"legend_symbol", "equipment_room_layout", "installation_detail", "rack_detail"}
_PRIORITY_OVERRIDES = {"legend_first", "mixed_detail_first"}


@dataclass(frozen=True, slots=True)
class _PolicySignals:
    sheet_type: str
    block_count: int
    table_count: int
    word_count: int
    table_density: float
    ambiguity: float
    note_density: float
    detail_density: float
    heading_count: int
    vector_grid_hits: int
    decomposition_confidence: float
    fragmentation_risk: float


@dataclass(frozen=True, slots=True)
class _PagePolicyDecision:
    page_index: int
    sheet_type: str
    provider_path: str
    reason_codes: tuple[str, ...]
    block_budget: int
    use_lightweight_layout: bool
    lightweight_priority_profile: str
    lightweight_priority_rank: int
    signals: _PolicySignals


def _clean(text: str) -> str:
    return " ".join(str(text or "").replace("\x00", " ").split()).strip()


def _to_bool(value: object, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    lowered = str(value or "").strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    return default


def _provider_enabled(registry: Mapping[str, Any], key: str, *, default: bool = True) -> bool:
    row = registry.get(key, {})
    if not isinstance(row, Mapping):
        return default
    return _to_bool(row.get("enabled", default), default=default)


def _table_cells_from_text(
    text: str,
    *,
    confidence: float,
    provider: str,
    source_mode: str,
) -> tuple[SiteSchematicTableCellObservation, ...]:
    rows = [row.strip() for row in str(text or "").split(";") if row.strip()]
    out: list[SiteSchematicTableCellObservation] = []
    for row_idx, row in enumerate(rows):
        cells = [cell.strip() for cell in row.split("|") if cell.strip()]
        for col_idx, cell in enumerate(cells):
            out.append(
                SiteSchematicTableCellObservation(
                    row_index=row_idx,
                    col_index=col_idx,
                    text=cell,
                    confidence=confidence,
                    source_mode=source_mode,
                    provider=provider,
                    metadata={"derived": True},
                )
            )
    return tuple(out)


def _fallback_observations(page_texts: list[str], *, reason: str) -> tuple[tuple[SiteSchematicPageObservation, ...], dict[str, Any]]:
    rows: list[SiteSchematicPageObservation] = []
    page_diagnostics: list[dict[str, Any]] = []
    for page_index, text in enumerate(page_texts, start=1):
        rows.append(
            SiteSchematicPageObservation(
                page_index=page_index,
                page_text=text,
                confidence=0.5,
                source_mode="text_heuristic",
                provider="text_heuristic",
                words=(),
                layout_blocks=(),
                reading_order=(),
                table_blocks=(),
                vector_items=(),
                metadata={"fallback": True, "reason": reason},
            )
        )
        page_diagnostics.append(
            {
                "page_index": page_index,
                "provider_path": "text_heuristic",
                "reason_codes": [reason],
                "native_block_count": 0,
                "merged_block_count": 0,
                "table_count": 0,
                "block_budget_applied": False,
                "clustering_applied": False,
            }
        )
    diagnostics = {
        "enabled": False,
        "used": False,
        "reason": reason,
        "winner": "text_heuristic",
        "provider_status": {},
        "pages": page_diagnostics,
    }
    return tuple(rows), diagnostics


def _block_role(text: str, *, line_count: int = 1, vector_grid_score: float = 0.0) -> str:
    lowered = text.lower()
    if not lowered:
        return "paragraph"
    if "|" in text or "\t" in text:
        return "table"
    if vector_grid_score >= 0.45 and any(token in lowered for token in ("legend", "schedule", "sheet", "symbol", "notes")):
        return "table"
    if any(token in lowered for token in ("legend", "abbreviation", "schedule", "matrix", "drawing index")):
        return "table"
    if line_count <= 2 and (text.isupper() or text.istitle()) and len(text) <= 120:
        return "heading"
    if text.startswith(("-", "*", "•")):
        return "bullet"
    return "paragraph"


def _is_table_block(text: str) -> bool:
    lowered = text.lower()
    return ("|" in text) or any(token in lowered for token in ("schedule", "legend", "abbreviation", "matrix", "sheet no", "drawing index"))


def _bbox_overlap_ratio(
    a: tuple[float, float, float, float] | None,
    b: tuple[float, float, float, float] | None,
) -> float:
    if a is None or b is None:
        return 0.0
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    area = max((ax1 - ax0) * (ay1 - ay0), 1.0)
    return inter / area


def _sort_blocks(blocks: list[SiteSchematicLayoutBlockObservation]) -> tuple[SiteSchematicLayoutBlockObservation, ...]:
    ordered = sorted(
        blocks,
        key=lambda row: (
            row.bbox[1] if row.bbox else 1e12,
            row.bbox[0] if row.bbox else 1e12,
            row.block_id,
        ),
    )
    out: list[SiteSchematicLayoutBlockObservation] = []
    for idx, row in enumerate(ordered, start=1):
        out.append(
            SiteSchematicLayoutBlockObservation(
                block_id=row.block_id,
                page_index=row.page_index,
                text=row.text,
                role=row.role,
                confidence=row.confidence,
                bbox=row.bbox,
                source_mode=row.source_mode,
                provider=row.provider,
                reading_order=idx,
                metadata=dict(row.metadata),
            )
        )
    return tuple(out)


def _extract_pdf_native_observations(
    *,
    path: Path,
    pdf_bytes: bytes | None,
    page_texts: list[str],
) -> tuple[tuple[SiteSchematicPageObservation, ...], dict[str, Any]]:
    try:
        import fitz  # type: ignore
    except Exception:
        return _fallback_observations(page_texts, reason="pdf_native_unavailable")

    try:
        document = fitz.open(stream=pdf_bytes, filetype="pdf") if pdf_bytes is not None else fitz.open(path)
    except Exception:
        return _fallback_observations(page_texts, reason="pdf_open_failed")

    observations: list[SiteSchematicPageObservation] = []
    page_diags: list[dict[str, Any]] = []
    for page_zero, page in enumerate(document):
        page_index = page_zero + 1
        page_words: list[SiteSchematicWordObservation] = []
        words = page.get_text("words") or []
        sorted_words = sorted(words, key=lambda row: (float(row[1]), float(row[0]), int(row[5]), int(row[6]), int(row[7])))
        for order, row in enumerate(sorted_words, start=1):
            if len(row) < 8:
                continue
            text = _clean(str(row[4]))
            if not text:
                continue
            page_words.append(
                SiteSchematicWordObservation(
                    word_id=f"word:p{page_index}:{order}",
                    page_index=page_index,
                    text=text,
                    bbox=(float(row[0]), float(row[1]), float(row[2]), float(row[3])),
                    reading_order=order,
                    confidence=0.92,
                    source_mode="pdf_native",
                    provider="fitz",
                    metadata={"block_no": int(row[5]), "line_no": int(row[6]), "word_no": int(row[7])},
                )
            )

        vectors: list[SiteSchematicVectorObservation] = []
        line_like_vectors: list[tuple[float, float, float, float]] = []
        try:
            drawing_rows = page.get_drawings() or []
        except Exception:
            drawing_rows = []
        image_count = 0
        try:
            image_count = len(page.get_images(full=True) or [])
        except Exception:
            image_count = 0
        for draw_idx, draw in enumerate(drawing_rows, start=1):
            bbox = None
            rect = draw.get("rect") if isinstance(draw, dict) else None
            if rect is not None:
                try:
                    bbox = (float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1))
                except Exception:
                    bbox = None
            vectors.append(
                SiteSchematicVectorObservation(
                    vector_id=f"vector:p{page_index}:{draw_idx}",
                    page_index=page_index,
                    kind=str(draw.get("type", "path")) if isinstance(draw, dict) else "path",
                    bbox=bbox,
                    confidence=0.78,
                    source_mode="pdf_native",
                    provider="fitz",
                    metadata={
                        "item_count": len(draw.get("items", [])) if isinstance(draw, dict) else 0,
                        "has_stroke": bool(draw.get("stroke")) if isinstance(draw, dict) else False,
                    },
                )
            )
            if bbox is not None:
                line_like_vectors.append(bbox)

        blocks: list[SiteSchematicLayoutBlockObservation] = []
        tables: list[SiteSchematicTableObservation] = []
        dict_data = page.get_text("dict") or {}
        block_rows = dict_data.get("blocks", []) if isinstance(dict_data, dict) else []
        for block_idx, block in enumerate(block_rows, start=1):
            if not isinstance(block, dict) or int(block.get("type", 0)) != 0:
                continue
            lines = block.get("lines", [])
            text_parts: list[str] = []
            line_count = 0
            for line in lines or []:
                spans = line.get("spans", []) if isinstance(line, dict) else []
                span_text = "".join(str(span.get("text", "")) for span in spans if isinstance(span, dict))
                cleaned_span = _clean(span_text)
                if cleaned_span:
                    text_parts.append(cleaned_span)
                    line_count += 1
            text = _clean(" ".join(text_parts))
            if not text:
                continue
            bbox = None
            raw_bbox = block.get("bbox")
            if isinstance(raw_bbox, (list, tuple)) and len(raw_bbox) >= 4:
                bbox = (float(raw_bbox[0]), float(raw_bbox[1]), float(raw_bbox[2]), float(raw_bbox[3]))
            grid_hits = 0
            if bbox is not None:
                for vbox in line_like_vectors[:250]:
                    if _bbox_overlap_ratio(bbox, vbox) > 0.2:
                        grid_hits += 1
            vector_grid_score = min(1.0, grid_hits / 6.0)
            role = _block_role(text, line_count=line_count, vector_grid_score=vector_grid_score)
            block_id = f"pdf_native_block:{page_zero:04d}:{block_idx:04d}"
            conf = 0.9 if role == "heading" else (0.84 if role == "table" else 0.82)
            blocks.append(
                SiteSchematicLayoutBlockObservation(
                    block_id=block_id,
                    page_index=page_index,
                    text=text,
                    role=role,
                    confidence=conf,
                    bbox=bbox,
                    source_mode="pdf_native",
                    provider="fitz",
                    reading_order=block_idx,
                    metadata={"line_count": line_count, "vector_grid_score": round(vector_grid_score, 4)},
                )
            )
            if role == "table" or _is_table_block(text) or vector_grid_score >= 0.65:
                table_id = f"pdf_native_table:{page_zero:04d}:{block_idx:04d}"
                tables.append(
                    SiteSchematicTableObservation(
                        table_id=table_id,
                        page_index=page_index,
                        text=text,
                        confidence=0.82,
                        bbox=bbox,
                        source_mode="pdf_native",
                        provider="fitz",
                        cells=_table_cells_from_text(text=text, confidence=0.75, provider="fitz", source_mode="pdf_native"),
                        metadata={"from_text_block": True, "vector_grid_score": round(vector_grid_score, 4)},
                    )
                )
        ordered_blocks = _sort_blocks(blocks)
        vector_path_count = len(vectors)
        line_art_density = min(1.0, vector_path_count / max(1.0, float(len(ordered_blocks)) * 4.0))
        page_text = "\n".join(row.text for row in ordered_blocks) or (page_texts[page_zero] if page_zero < len(page_texts) else "")
        observations.append(
            SiteSchematicPageObservation(
                page_index=page_index,
                page_text=page_text,
                confidence=0.86,
                source_mode="pdf_native",
                provider="fitz",
                words=tuple(page_words),
                layout_blocks=ordered_blocks,
                reading_order=tuple(row.block_id for row in ordered_blocks),
                table_blocks=tuple(tables),
                vector_items=tuple(vectors),
                metadata={
                    "native_word_count": len(page_words),
                    "native_block_count": len(ordered_blocks),
                    "native_table_count": len(tables),
                    "native_vector_count": len(vectors),
                    "vector_path_count": vector_path_count,
                    "image_count": image_count,
                    "line_art_density": round(line_art_density, 4),
                },
            )
        )
        page_diags.append(
            {
                "page_index": page_index,
                "provider_path": "pdf_native",
                "reason_codes": ["pdf_native_first_pass"],
                "native_block_count": len(ordered_blocks),
                "merged_block_count": len(ordered_blocks),
                "table_count": len(tables),
                "vector_path_count": vector_path_count,
                "image_count": image_count,
                "line_art_density": round(line_art_density, 4),
                "block_budget_applied": False,
                "clustering_applied": False,
            }
        )

    diagnostics = {
        "enabled": True,
        "used": bool(observations),
        "winner": "pdf_native",
        "reason": "pdf_native_first",
        "provider_status": {"pdf_native": {"enabled": True, "available": bool(observations), "availability_reason": "ok"}},
        "pages": page_diags,
    }
    return tuple(observations), diagnostics


def _page_complexity_metrics(page: SiteSchematicPageObservation) -> dict[str, float]:
    block_count = len(page.layout_blocks)
    table_count = len(page.table_blocks)
    word_count = len(page.words)
    table_density = table_count / max(1, block_count)
    ambiguity = 1.0 if block_count > 180 else (0.6 if block_count > 120 else (0.3 if block_count > 80 else 0.0))
    return {
        "block_count": float(block_count),
        "table_count": float(table_count),
        "word_count": float(word_count),
        "table_density": table_density,
        "ambiguity": ambiguity,
    }


def _compute_policy_signals(
    *,
    page: SiteSchematicPageObservation,
    sheet_type: str,
) -> _PolicySignals:
    metrics = _page_complexity_metrics(page)
    text_rows = [str(row.text).lower() for row in page.layout_blocks if row.text]
    block_count = int(metrics["block_count"])
    table_count = int(metrics["table_count"])
    note_hits = sum(1 for row in text_rows if any(token in row for token in ("note", "spec", "general notes", "keyed note")))
    detail_hits = sum(1 for row in text_rows if any(token in row for token in ("detail", "elevation", "rack", "equipment", "riser", "guestroom")))
    heading_count = sum(1 for row in page.layout_blocks if row.role == "heading")
    vector_grid_hits = sum(
        1
        for row in page.layout_blocks
        if float((row.metadata or {}).get("vector_grid_score", 0.0)) >= 0.45
    )
    note_density = note_hits / max(1, block_count)
    detail_density = detail_hits / max(1, block_count)
    table_density = float(metrics["table_density"])
    ambiguity = float(metrics["ambiguity"])
    decomposition_confidence = max(0.05, min(0.98, 1.0 - (ambiguity * 0.55) - min(0.35, table_density * 0.4)))
    fragmentation_risk = max(
        0.0,
        min(
            1.0,
            (block_count / 190.0)
            + (table_density * 0.35)
            + (0.28 if sheet_type in _MIXED_DETAIL_SHEETS else 0.0)
            + (0.16 if note_density >= 0.22 and detail_density >= 0.2 else 0.0),
        ),
    )
    return _PolicySignals(
        sheet_type=sheet_type or "unknown",
        block_count=block_count,
        table_count=table_count,
        word_count=int(metrics["word_count"]),
        table_density=table_density,
        ambiguity=ambiguity,
        note_density=note_density,
        detail_density=detail_density,
        heading_count=heading_count,
        vector_grid_hits=vector_grid_hits,
        decomposition_confidence=decomposition_confidence,
        fragmentation_risk=fragmentation_risk,
    )


def _select_provider_path(
    *,
    signals: _PolicySignals,
    force_docling_all_pages: bool,
) -> tuple[str, list[str]]:
    if force_docling_all_pages:
        return "native_docling_full", ["forced_docling_all_pages"]
    reasons: list[str] = [
        f"sheet_type:{signals.sheet_type}",
        f"native_blocks:{signals.block_count}",
        f"fragmentation_risk:{signals.fragmentation_risk:.3f}",
    ]
    block_count = signals.block_count
    table_count = signals.table_count
    ambiguity = signals.ambiguity
    sheet_type = signals.sheet_type
    if sheet_type in _AGGRESSIVE_DOCILING_SHEETS:
        reasons.append("aggressive_sheet_policy")
        if block_count > 180 or ambiguity >= 0.6 or signals.note_density >= 0.24:
            reasons.append("high_complexity_or_ambiguity")
            return "native_docling_full", reasons
        return "native_docling_limited", reasons
    if sheet_type in _CONSERVATIVE_DOCILING_SHEETS:
        reasons.append("conservative_sheet_policy")
        if sheet_type in _MIXED_DETAIL_SHEETS and (
            (table_count >= 4 and ambiguity >= 0.3) or block_count >= 95
        ):
            reasons.append("mixed_detail_complexity_escalation")
            return "native_docling_limited", reasons
        return "native_only", reasons
    if table_count >= 6 or ambiguity >= 0.6:
        reasons.append("generic_complex_page")
        return "native_docling_limited", reasons
    return "native_only", reasons


def _select_lightweight_priority_profile(
    *,
    signals: _PolicySignals,
    cfg: Mapping[str, Any],
) -> tuple[str, list[str]]:
    debug_override = str(cfg.get("debug_priority_mode_override", "")).strip().lower()
    override = debug_override or str(cfg.get("lightweight_layout_priority_mode", "auto")).strip().lower()
    reasons: list[str] = []
    if override in _PRIORITY_OVERRIDES:
        reasons.append(f"priority_override:{override}")
        return override, reasons
    if signals.sheet_type == "legend_symbol" and (signals.table_count >= 5 or signals.vector_grid_hits >= 3):
        reasons.append("dynamic_priority:legend_dense")
        return "legend_first", reasons
    if signals.sheet_type in _MIXED_DETAIL_SHEETS and (
        signals.fragmentation_risk >= 0.62 or signals.detail_density >= 0.25
    ):
        reasons.append("dynamic_priority:mixed_detail_dense")
        return "mixed_detail_first", reasons
    if signals.note_density >= 0.28 and signals.table_density >= 0.25:
        reasons.append("dynamic_priority:legend_note_mix")
        return "legend_first", reasons
    reasons.append("dynamic_priority:balanced_default")
    return "balanced_auto", reasons


def _should_use_lightweight_layout(
    *,
    signals: _PolicySignals,
    provider_path: str,
    cfg: Mapping[str, Any],
) -> tuple[bool, list[str]]:
    if not _to_bool(cfg.get("lightweight_layout_enabled", True), default=True):
        return False, ["lightweight_disabled"]
    sheet_type = signals.sheet_type
    if sheet_type not in _LIGHTWEIGHT_LAYOUT_SHEETS:
        return False, [f"sheet_not_targeted:{sheet_type or 'unknown'}"]
    block_count = signals.block_count
    table_count = signals.table_count
    ambiguity = signals.ambiguity
    reasons: list[str] = [f"sheet_type:{sheet_type or 'unknown'}", f"native_blocks:{block_count}"]
    if sheet_type in _MIXED_DETAIL_SHEETS and ((table_count >= 3 and ambiguity >= 0.3) or block_count >= 85):
        reasons.append("mixed_detail_layout_hint")
        return True, reasons
    if sheet_type == "legend_symbol" and table_count >= 6:
        reasons.append("legend_table_density")
        return True, reasons
    if signals.fragmentation_risk >= 0.66 and (signals.note_density >= 0.2 or signals.detail_density >= 0.25):
        reasons.append("high_fragmentation_risk")
        return True, reasons
    if provider_path == "native_docling_limited" and ambiguity >= 0.6:
        reasons.append("docling_limited_but_ambiguous")
        return True, reasons
    reasons.append("layout_not_needed")
    return False, reasons


def _budget_for_policy(*, sheet_type: str, provider_path: str, cfg: Mapping[str, Any]) -> int:
    default_native = int(cfg.get("native_block_budget", 120))
    default_limited = int(cfg.get("docling_limited_block_budget", 140))
    default_full = int(cfg.get("docling_full_block_budget", 220))
    if sheet_type in _MIXED_DETAIL_SHEETS:
        default_native = min(default_native, int(cfg.get("mixed_detail_native_budget", 60)))
        default_limited = min(default_limited, int(cfg.get("mixed_detail_docling_budget", 90)))
        default_full = min(default_full, int(cfg.get("mixed_detail_docling_budget", 90)))
    if provider_path == "native_only":
        return max(20, default_native)
    if provider_path == "native_docling_limited":
        return max(30, default_limited)
    return max(40, default_full)


def _limit_lightweight_pages(
    *,
    policies: list[_PagePolicyDecision],
    max_pages: int,
) -> list[int]:
    if max_pages <= 0:
        return []
    selected = [row for row in policies if row.use_lightweight_layout]
    if len(selected) <= max_pages:
        return [row.page_index for row in selected]

    ranked = sorted(
        selected,
        key=lambda row: (
            row.lightweight_priority_rank,
            0 if row.sheet_type in {"legend_symbol", "equipment_room_layout"} else 1,
            -row.signals.fragmentation_risk,
            -row.signals.block_count,
            -row.signals.detail_density,
            -row.signals.table_density,
            row.page_index,
        ),
    )
    return [row.page_index for row in ranked[:max_pages]]


def _build_page_policy(
    *,
    page: SiteSchematicPageObservation,
    sheet_type: str,
    force_docling_all_pages: bool,
    cfg: Mapping[str, Any],
    lightweight_enabled: bool,
) -> _PagePolicyDecision:
    signals = _compute_policy_signals(page=page, sheet_type=sheet_type)
    provider_path, provider_reasons = _select_provider_path(
        signals=signals,
        force_docling_all_pages=force_docling_all_pages,
    )
    use_lightweight, lightweight_reasons = _should_use_lightweight_layout(
        signals=signals,
        provider_path=provider_path,
        cfg=cfg,
    )
    priority_profile, priority_reasons = _select_lightweight_priority_profile(signals=signals, cfg=cfg)
    priority_rank = 2
    if priority_profile == "legend_first":
        priority_rank = 0 if signals.sheet_type == "legend_symbol" else 1
    elif priority_profile == "mixed_detail_first":
        priority_rank = 0 if signals.sheet_type in _MIXED_DETAIL_SHEETS else 1
    elif signals.fragmentation_risk >= 0.7:
        priority_rank = 0
    budget = _budget_for_policy(sheet_type=sheet_type, provider_path=provider_path, cfg=cfg)
    reason_codes = tuple([*provider_reasons, *priority_reasons, *lightweight_reasons])
    return _PagePolicyDecision(
        page_index=page.page_index,
        sheet_type=sheet_type,
        provider_path=provider_path,
        reason_codes=reason_codes,
        block_budget=budget,
        use_lightweight_layout=bool(use_lightweight and lightweight_enabled),
        lightweight_priority_profile=priority_profile,
        lightweight_priority_rank=priority_rank,
        signals=signals,
    )


def _extract_docling_for_selected_pages(
    *,
    path: Path,
    pdf_bytes: bytes | None,
    selected_pages: list[int],
) -> dict[int, Any]:
    if not selected_pages:
        return {}
    try:
        import fitz  # type: ignore
    except Exception:
        return {}
    hypotheses: dict[int, Any] = {}
    doc = fitz.open(stream=pdf_bytes, filetype="pdf") if pdf_bytes is not None else fitz.open(path)
    for page_index in selected_pages:
        page_zero = page_index - 1
        if page_zero < 0 or page_zero >= len(doc):
            continue
        tmp_name = ""
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp_name = tmp.name
            out = fitz.open()
            out.insert_pdf(doc, from_page=page_zero, to_page=page_zero)
            out.save(tmp_name)
            out.close()
            hypothesis = extract_docling_pdf_hypothesis(pdf_path=Path(tmp_name))
            if hypothesis is not None:
                hypotheses[page_index] = hypothesis
        except Exception:
            continue
        finally:
            if tmp_name:
                try:
                    Path(tmp_name).unlink(missing_ok=True)
                except Exception:
                    pass
    doc.close()
    return hypotheses


def _expand_clip_bbox(
    *,
    bbox: tuple[float, float, float, float],
    page_width: float,
    page_height: float,
    pad: float,
) -> tuple[float, float, float, float] | None:
    x0, y0, x1, y1 = bbox
    if x1 <= x0 or y1 <= y0:
        return None
    ex0 = max(0.0, x0 - pad)
    ey0 = max(0.0, y0 - pad)
    ex1 = min(page_width, x1 + pad)
    ey1 = min(page_height, y1 + pad)
    if ex1 <= ex0 or ey1 <= ey0:
        return None
    return (ex0, ey0, ex1, ey1)


def _target_lightweight_candidate_bboxes(
    *,
    page: SiteSchematicPageObservation,
    sheet_type: str,
    cfg: Mapping[str, Any],
) -> list[tuple[float, float, float, float]]:
    max_candidates = max(1, int(cfg.get("lightweight_layout_crop_max_candidates", 2)))
    rows: list[tuple[int, float, tuple[float, float, float, float]]] = []
    for table in page.table_blocks:
        if table.bbox is None:
            continue
        rows.append((0, float(table.confidence), table.bbox))
    for block in page.layout_blocks:
        if block.bbox is None:
            continue
        body = block.text.lower()
        if block.role == "table" and any(token in body for token in ("legend", "symbol", "schedule", "matrix", "table", "index")):
            rows.append((1, float(block.confidence), block.bbox))
            continue
        if sheet_type in _MIXED_DETAIL_SHEETS and any(token in body for token in ("detail", "equipment", "elevation", "rack", "cabinet", "guestroom", "notes")):
            rows.append((2, float(block.confidence), block.bbox))
    rows.sort(key=lambda row: (row[0], -row[1]))
    selected: list[tuple[float, float, float, float]] = []
    for _, _, bbox in rows:
        if any(_bbox_overlap_ratio(bbox, existing) > 0.72 for existing in selected):
            continue
        selected.append(bbox)
        if len(selected) >= max_candidates:
            break
    return selected


def _extract_lightweight_layout_for_page_crops(
    *,
    path: Path,
    pdf_bytes: bytes | None,
    page: SiteSchematicPageObservation,
    sheet_type: str,
    cfg: Mapping[str, Any],
) -> tuple[Any | None, dict[str, Any]]:
    try:
        import fitz  # type: ignore
        import numpy as np  # type: ignore
        import cv2  # type: ignore
    except Exception:
        return None, {"lightweight_crop_count": 0}
    page_index = page.page_index
    doc = fitz.open(stream=pdf_bytes, filetype="pdf") if pdf_bytes is not None else fitz.open(path)
    try:
        page_zero = page_index - 1
        if page_zero < 0 or page_zero >= len(doc):
            return None, {"lightweight_crop_count": 0}
        doc_page = doc[page_zero]
        candidates = _target_lightweight_candidate_bboxes(page=page, sheet_type=sheet_type, cfg=cfg)
        if not candidates:
            return None, {"lightweight_crop_count": 0}
        pad = float(cfg.get("lightweight_layout_crop_padding", 18.0))
        matrix_scale = float(cfg.get("lightweight_layout_crop_scale", 0.85))
        crop_hypotheses: list[Any] = []
        for idx, bbox in enumerate(candidates, start=1):
            clip_bbox = _expand_clip_bbox(
                bbox=bbox,
                page_width=float(doc_page.rect.width),
                page_height=float(doc_page.rect.height),
                pad=pad,
            )
            if clip_bbox is None:
                continue
            rect = fitz.Rect(*clip_bbox)
            pix = doc_page.get_pixmap(matrix=fitz.Matrix(matrix_scale, matrix_scale), clip=rect, alpha=False)
            img = cv2.imdecode(np.frombuffer(pix.tobytes("png"), dtype=np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                continue
            hypothesis = extract_pp_structure_image_hypothesis(
                image_array=img,
                page_index=page_zero,
                source_tag=f"crop:{page_index}:{idx}",
                bbox_offset=(float(rect.x0), float(rect.y0)),
            )
            if hypothesis is None:
                continue
            crop_hypotheses.append(hypothesis)
        if not crop_hypotheses:
            if _to_bool(cfg.get("lightweight_layout_crop_fallback_full_page", True), default=True):
                fallback_scale = float(cfg.get("lightweight_layout_fallback_scale", 0.45))
                pix = doc_page.get_pixmap(matrix=fitz.Matrix(fallback_scale, fallback_scale), alpha=False)
                img = cv2.imdecode(np.frombuffer(pix.tobytes("png"), dtype=np.uint8), cv2.IMREAD_COLOR)
                if img is not None:
                    fallback_hypothesis = extract_pp_structure_image_hypothesis(
                        image_array=img,
                        page_index=page_zero,
                        source_tag=f"fallback_full_page:{page_index}",
                    )
                    if fallback_hypothesis is not None:
                        return fallback_hypothesis, {
                            "lightweight_crop_count": len(candidates),
                            "lightweight_full_page_fallback": True,
                        }
            return None, {"lightweight_crop_count": len(candidates), "lightweight_full_page_fallback": False}
        merged_blocks: list[Any] = []
        merged_tables: list[Any] = []
        confidence_rows: list[float] = []
        for hypothesis in crop_hypotheses:
            merged_blocks.extend(tuple(getattr(hypothesis, "page_blocks", ())))
            merged_tables.extend(tuple(getattr(hypothesis, "table_regions", ())))
            confidence_rows.append(float(getattr(hypothesis, "confidence", 0.0)))
        merged = ProviderPdfHypothesis(
            hypothesis_id=f"hypothesis:pp_structure:page:{page_index}:crops",
            source="pp_structure",
            page_blocks=tuple(merged_blocks),
            table_regions=tuple(merged_tables),
            confidence=(sum(confidence_rows) / len(confidence_rows)) if confidence_rows else 0.0,
            metadata={"source_mode": "targeted_crops", "crop_count": len(crop_hypotheses)},
        )
        return merged, {"lightweight_crop_count": len(crop_hypotheses)}
    finally:
        doc.close()


def _lightweight_hint_kind(text: str, role: str, meta: Mapping[str, Any]) -> str:
    lowered = text.lower()
    pp_type = str(meta.get("pp_type", "")).lower()
    if role == "table" or "table" in pp_type:
        return "table_grid"
    if "legend" in lowered or "symbol" in lowered or "abbreviation" in lowered or "matrix" in lowered:
        return "legend_grid"
    if "note" in lowered or "specification" in lowered:
        return "notes_column"
    if "revision" in lowered or "issue" in lowered or "print date" in lowered:
        return "revision_rail"
    if "title" in lowered or "sheet no" in lowered or "drawing title" in lowered or role == "heading":
        return "title_block"
    if any(token in lowered for token in ("detail", "elevation", "rack", "guestroom", "equipment")):
        return "detail_group"
    return "body_layout"


def _merge_page_lightweight_layout(
    *,
    page: SiteSchematicPageObservation,
    sheet_type: str,
    enabled_for_page: bool,
    cfg: Mapping[str, Any],
    layout_hypothesis: Any | None,
) -> tuple[SiteSchematicPageObservation, dict[str, Any]]:
    if not enabled_for_page or layout_hypothesis is None:
        return page, {
            "lightweight_layout_used": False,
            "layout_blocks_added": 0,
            "layout_tables_added": 0,
            "layout_block_budget_applied": False,
        }
    min_conf = float(cfg.get("lightweight_layout_min_confidence", 0.58))
    default_cap = int(cfg.get("lightweight_layout_block_cap", 20))
    mixed_cap = int(cfg.get("mixed_detail_lightweight_cap", 14))
    cap = mixed_cap if sheet_type in _MIXED_DETAIL_SHEETS else default_cap

    incoming_blocks = tuple(getattr(layout_hypothesis, "page_blocks", ()))
    incoming_tables = tuple(getattr(layout_hypothesis, "table_regions", ()))
    merged_blocks = list(page.layout_blocks)
    merged_tables = list(page.table_blocks)
    seen_block_keys = {(row.text.lower(), row.role) for row in merged_blocks}
    seen_table_text = {row.text.lower() for row in merged_tables}

    grouped: dict[str, list[Any]] = defaultdict(list)
    for row in incoming_blocks:
        text = _clean(getattr(row, "text", ""))
        conf = float(getattr(row, "confidence", 0.0))
        if not text or conf < min_conf:
            continue
        role = str(getattr(row, "role", "paragraph") or "paragraph")
        meta = dict(getattr(row, "metadata", {}) or {})
        kind = _lightweight_hint_kind(text, role, meta)
        if kind == "body_layout" and role == "paragraph":
            continue
        grouped[kind].append(row)

    selected_rows: list[Any] = []
    for _, rows in grouped.items():
        ranked = sorted(rows, key=lambda item: float(getattr(item, "confidence", 0.0)), reverse=True)
        selected_rows.extend(ranked[:2])
    selected_rows = sorted(
        selected_rows,
        key=lambda item: (
            float(getattr(item, "bbox", (0.0, 1e12, 0.0, 1e12))[1]) if getattr(item, "bbox", None) else 1e12,
            -float(getattr(item, "confidence", 0.0)),
        ),
    )[: max(1, cap)]

    layout_blocks_added = 0
    for item in selected_rows:
        text = _clean(getattr(item, "text", ""))
        role = str(getattr(item, "role", "paragraph") or "paragraph")
        conf = float(getattr(item, "confidence", 0.0))
        meta = dict(getattr(item, "metadata", {}) or {})
        hint_kind = _lightweight_hint_kind(text, role, meta)
        if hint_kind in {"table_grid", "legend_grid"}:
            role = "table"
        elif hint_kind == "title_block":
            role = "heading"
        key = (text.lower(), role)
        if key in seen_block_keys:
            continue
        merged_blocks.append(
            SiteSchematicLayoutBlockObservation(
                block_id=str(getattr(item, "block_id", f"lightweight_block:p{page.page_index}:{len(merged_blocks)+1}")),
                page_index=page.page_index,
                text=text,
                role=role,
                confidence=max(0.45, min(0.96, conf)),
                bbox=getattr(item, "bbox", None),
                source_mode="layout_lightweight",
                provider="pp_structure",
                reading_order=0,
                metadata={**meta, "layout_hint_kind": hint_kind},
            )
        )
        seen_block_keys.add(key)
        layout_blocks_added += 1

    layout_tables_added = 0
    for table in incoming_tables[: max(3, cap // 2)]:
        text = _clean(getattr(table, "text", ""))
        conf = float(getattr(table, "confidence", 0.0))
        if not text or conf < min_conf:
            continue
        key = text.lower()
        if key in seen_table_text:
            continue
        merged_tables.append(
            SiteSchematicTableObservation(
                table_id=str(getattr(table, "region_id", f"lightweight_table:p{page.page_index}:{len(merged_tables)+1}")),
                page_index=page.page_index,
                text=text,
                confidence=max(0.45, min(0.95, conf)),
                bbox=getattr(table, "bbox", None),
                source_mode="layout_lightweight",
                provider="pp_structure",
                cells=_table_cells_from_text(text=text, confidence=0.7, provider="pp_structure", source_mode="layout_lightweight"),
                metadata={**dict(getattr(table, "metadata", {}) or {}), "layout_hint_kind": "table_grid"},
            )
        )
        seen_table_text.add(key)
        layout_tables_added += 1

    ordered_blocks = list(_sort_blocks(merged_blocks))
    base_budget = int(page.metadata.get("block_budget", max(20, len(page.layout_blocks))))
    final_cap = max(base_budget, min(base_budget + cap, base_budget + 24))
    layout_budget_applied = False
    if len(ordered_blocks) > final_cap:
        layout_budget_applied = True
        prioritized = sorted(
            ordered_blocks,
            key=lambda row: (
                0 if row.role in {"table", "heading"} else 1,
                0 if str(row.source_mode) == "layout_lightweight" else 1,
                row.bbox[1] if row.bbox else 1e12,
                -row.confidence,
            ),
        )[:final_cap]
        ordered_blocks = list(_sort_blocks(prioritized))

    out = SiteSchematicPageObservation(
        page_index=page.page_index,
        page_text="\n".join(row.text for row in ordered_blocks) or page.page_text,
        confidence=max(page.confidence, 0.8),
        source_mode=f"{page.source_mode}+layout_lightweight",
        provider=f"{page.provider}+pp_structure",
        words=page.words,
        layout_blocks=tuple(ordered_blocks),
        reading_order=tuple(row.block_id for row in ordered_blocks),
        table_blocks=tuple(merged_tables),
        vector_items=page.vector_items,
        metadata={
            **dict(page.metadata),
            "lightweight_layout_used": True,
            "layout_block_cap": cap,
            "layout_blocks_added": layout_blocks_added,
            "layout_tables_added": layout_tables_added,
            "layout_block_budget_applied": layout_budget_applied,
            "merged_block_count": len(ordered_blocks),
        },
    )
    return out, {
        "lightweight_layout_used": True,
        "layout_blocks_added": layout_blocks_added,
        "layout_tables_added": layout_tables_added,
        "layout_block_budget_applied": layout_budget_applied,
    }


def _merge_page_docling(
    *,
    page: SiteSchematicPageObservation,
    sheet_type: str,
    provider_path: str,
    budget: int,
    docling_hypothesis: Any | None,
) -> tuple[SiteSchematicPageObservation, dict[str, Any]]:
    native_blocks = list(page.layout_blocks)
    merged_blocks = list(native_blocks)
    merged_tables = list(page.table_blocks)
    docling_blocks_added = 0
    docling_tables_added = 0
    if docling_hypothesis is not None and provider_path != "native_only":
        seen_keys = {(row.text.lower(), row.role) for row in merged_blocks}
        for block in tuple(getattr(docling_hypothesis, "page_blocks", ())):
            text = _clean(getattr(block, "text", ""))
            if not text:
                continue
            role = str(getattr(block, "role", "paragraph") or "paragraph")
            conf = float(getattr(block, "confidence", 0.0))
            if provider_path == "native_docling_limited" and role == "paragraph" and conf < 0.85:
                continue
            if provider_path == "native_docling_limited" and role == "paragraph" and len(text) > 220:
                continue
            key = (text.lower(), role)
            if key in seen_keys:
                continue
            merged_blocks.append(
                SiteSchematicLayoutBlockObservation(
                    block_id=str(getattr(block, "block_id", f"docling_block:p{page.page_index}:{len(merged_blocks)+1}")),
                    page_index=page.page_index,
                    text=text,
                    role=role,
                    confidence=max(0.45, conf),
                    bbox=getattr(block, "bbox", None),
                    source_mode="docling_refined",
                    provider="docling",
                    reading_order=0,
                    metadata=dict(getattr(block, "metadata", {}) or {}),
                )
            )
            seen_keys.add(key)
            docling_blocks_added += 1
        seen_tables = {row.text.lower() for row in merged_tables}
        for table in tuple(getattr(docling_hypothesis, "table_regions", ())):
            text = _clean(getattr(table, "text", ""))
            if not text:
                continue
            key = text.lower()
            if key in seen_tables:
                continue
            merged_tables.append(
                SiteSchematicTableObservation(
                    table_id=str(getattr(table, "region_id", f"docling_table:p{page.page_index}:{len(merged_tables)+1}")),
                    page_index=page.page_index,
                    text=text,
                    confidence=max(0.45, float(getattr(table, "confidence", 0.0))),
                    bbox=getattr(table, "bbox", None),
                    source_mode="docling_refined",
                    provider="docling",
                    cells=_table_cells_from_text(
                        text=text,
                        confidence=0.72,
                        provider="docling",
                        source_mode="docling_refined",
                    ),
                    metadata=dict(getattr(table, "metadata", {}) or {}),
                )
            )
            seen_tables.add(key)
            docling_tables_added += 1
    ordered_blocks = list(_sort_blocks(merged_blocks))
    budget_applied = False
    if len(ordered_blocks) > budget:
        budget_applied = True
        tables = [row for row in ordered_blocks if row.role == "table"]
        headings = [row for row in ordered_blocks if row.role == "heading"]
        body = [row for row in ordered_blocks if row.role not in {"table", "heading"}]
        kept = tables[: max(2, budget // 4)] + headings[: max(2, budget // 6)] + body
        kept = sorted(
            kept,
            key=lambda row: (
                row.bbox[1] if row.bbox else 1e12,
                row.bbox[0] if row.bbox else 1e12,
                -row.confidence,
            ),
        )[:budget]
        ordered_blocks = list(_sort_blocks(kept))
    merged_text = "\n".join(row.text for row in ordered_blocks) or page.page_text
    out = SiteSchematicPageObservation(
        page_index=page.page_index,
        page_text=merged_text,
        confidence=max(page.confidence, 0.8),
        source_mode="pdf_native_docling" if provider_path != "native_only" else "pdf_native",
        provider="fitz+docling" if provider_path != "native_only" else "fitz",
        words=page.words,
        layout_blocks=tuple(ordered_blocks),
        reading_order=tuple(row.block_id for row in ordered_blocks),
        table_blocks=tuple(merged_tables),
        vector_items=page.vector_items,
        metadata={
            **dict(page.metadata),
            "provider_path": provider_path,
            "block_budget": budget,
            "block_budget_applied": budget_applied,
            "native_block_count": len(page.layout_blocks),
            "merged_block_count": len(ordered_blocks),
            "docling_blocks_added": docling_blocks_added,
            "docling_tables_added": docling_tables_added,
        },
    )
    diag = {
        "page_index": page.page_index,
        "provider_path": provider_path,
        "native_block_count": len(page.layout_blocks),
        "merged_block_count": len(ordered_blocks),
        "table_count": len(merged_tables),
        "block_budget": budget,
        "block_budget_applied": budget_applied,
        "docling_blocks_added": docling_blocks_added,
        "docling_tables_added": docling_tables_added,
    }
    return out, diag


def build_site_schematic_page_observations(
    *,
    router_input: RouterInput,
    page_texts: list[str],
    model_registry: Mapping[str, Any],
    sheet_types: list[str] | None = None,
) -> tuple[tuple[SiteSchematicPageObservation, ...], dict[str, Any]]:
    path = extract_path(router_input)
    pdf_bytes = extract_bytes(router_input)
    if path is None or path.suffix.lower() != ".pdf":
        return _fallback_observations(page_texts, reason="non_pdf_input")

    observation_cfg = model_registry.get("observation_layer", {})
    observation_enabled = _to_bool(
        observation_cfg.get("enabled", True) if isinstance(observation_cfg, Mapping) else True,
        default=True,
    )
    if not observation_enabled:
        return _fallback_observations(page_texts, reason="observation_layer_disabled")

    native_observations, native_diag = _extract_pdf_native_observations(path=path, pdf_bytes=pdf_bytes, page_texts=page_texts)
    if not native_diag.get("used"):
        return native_observations, native_diag

    docling_enabled = _provider_enabled(model_registry, "pdf_backbone", default=True) and _to_bool(
        observation_cfg.get("docling_merge_enabled", True) if isinstance(observation_cfg, Mapping) else True,
        default=True,
    )
    lightweight_enabled = _provider_enabled(model_registry, "layout_lightweight", default=True) and _to_bool(
        observation_cfg.get("lightweight_layout_enabled", True) if isinstance(observation_cfg, Mapping) else True,
        default=True,
    )
    force_docling_all_pages = _to_bool(
        observation_cfg.get("force_docling_all_pages", False) if isinstance(observation_cfg, Mapping) else False,
        default=False,
    )
    page_sheet_types = list(sheet_types or ["unknown"] * len(native_observations))
    policies: list[_PagePolicyDecision] = []
    selected_docling_pages: list[int] = []
    for page in native_observations:
        sheet_type = page_sheet_types[page.page_index - 1] if page.page_index - 1 < len(page_sheet_types) else "unknown"
        policy = _build_page_policy(
            page=page,
            sheet_type=sheet_type,
            force_docling_all_pages=force_docling_all_pages,
            cfg=observation_cfg if isinstance(observation_cfg, Mapping) else {},
            lightweight_enabled=lightweight_enabled,
        )
        policies.append(policy)
        if policy.provider_path != "native_only" and docling_enabled:
            selected_docling_pages.append(page.page_index)
    selected_lightweight_pages = _limit_lightweight_pages(
        policies=policies,
        max_pages=int(observation_cfg.get("lightweight_layout_page_cap", 3)) if isinstance(observation_cfg, Mapping) else 3,
    )
    selected_lightweight_set = set(selected_lightweight_pages)
    policies = [
        _PagePolicyDecision(
            page_index=row.page_index,
            sheet_type=row.sheet_type,
            provider_path=row.provider_path,
            reason_codes=row.reason_codes,
            block_budget=row.block_budget,
            use_lightweight_layout=row.use_lightweight_layout and row.page_index in selected_lightweight_set,
            lightweight_priority_profile=row.lightweight_priority_profile,
            lightweight_priority_rank=row.lightweight_priority_rank,
            signals=row.signals,
        )
        for row in policies
    ]
    docling_hypotheses_by_page = _extract_docling_for_selected_pages(path=path, pdf_bytes=pdf_bytes, selected_pages=selected_docling_pages)
    docling_cfg = model_registry.get("pdf_backbone", {})
    lightweight_cfg = model_registry.get("layout_lightweight", {})
    provider_status = dict(native_diag.get("provider_status", {}))
    provider_status["docling"] = {
        "enabled": docling_enabled,
        "available": bool(docling_hypotheses_by_page),
        "availability_reason": str(docling_cfg.get("availability_reason", "")) if isinstance(docling_cfg, Mapping) else "",
        "selected_page_count": len(selected_docling_pages),
    }
    provider_status["layout_lightweight"] = {
        "enabled": lightweight_enabled,
        "available": False,
        "availability_reason": str(lightweight_cfg.get("availability_reason", "")) if isinstance(lightweight_cfg, Mapping) else "",
        "selected_page_count": len(selected_lightweight_pages),
        "selection_mode": "dynamic" if str(observation_cfg.get("lightweight_layout_priority_mode", "auto")).strip().lower() not in _PRIORITY_OVERRIDES else "preset_override",
    }

    final_pages: list[SiteSchematicPageObservation] = []
    page_diags: list[dict[str, Any]] = []
    lightweight_success_count = 0
    for page in native_observations:
        policy = next((row for row in policies if row.page_index == page.page_index), None)
        if policy is None:
            policy = _PagePolicyDecision(
                page_index=page.page_index,
                sheet_type="unknown",
                provider_path="native_only",
                reason_codes=("policy_default",),
                block_budget=120,
                use_lightweight_layout=False,
                lightweight_priority_profile="balanced_auto",
                lightweight_priority_rank=9,
                signals=_compute_policy_signals(page=page, sheet_type="unknown"),
            )
        merged_page, merge_diag = _merge_page_docling(
            page=page,
            sheet_type=policy.sheet_type,
            provider_path=policy.provider_path,
            budget=policy.block_budget,
            docling_hypothesis=docling_hypotheses_by_page.get(page.page_index),
        )
        layout_hypothesis = None
        layout_extract_diag: dict[str, Any] = {"lightweight_crop_count": 0}
        if policy.use_lightweight_layout:
            layout_hypothesis, layout_extract_diag = _extract_lightweight_layout_for_page_crops(
                path=path,
                pdf_bytes=pdf_bytes,
                page=merged_page,
                sheet_type=policy.sheet_type,
                cfg=observation_cfg if isinstance(observation_cfg, Mapping) else {},
            )
            if layout_hypothesis is not None:
                lightweight_success_count += 1
        merged_page, layout_diag = _merge_page_lightweight_layout(
            page=merged_page,
            sheet_type=policy.sheet_type,
            enabled_for_page=policy.use_lightweight_layout,
            cfg=observation_cfg if isinstance(observation_cfg, Mapping) else {},
            layout_hypothesis=layout_hypothesis,
        )
        final_pages.append(merged_page)
        page_diags.append(
            {
                "page_index": policy.page_index,
                "sheet_type": policy.sheet_type,
                "provider_path": policy.provider_path,
                "reason_codes": list(policy.reason_codes),
                "block_budget": policy.block_budget,
                "use_lightweight_layout": policy.use_lightweight_layout,
                "lightweight_priority_profile": policy.lightweight_priority_profile,
                "lightweight_priority_rank": policy.lightweight_priority_rank,
                "policy_signals": {
                    "block_count": policy.signals.block_count,
                    "table_count": policy.signals.table_count,
                    "word_count": policy.signals.word_count,
                    "table_density": round(policy.signals.table_density, 4),
                    "ambiguity": round(policy.signals.ambiguity, 4),
                    "note_density": round(policy.signals.note_density, 4),
                    "detail_density": round(policy.signals.detail_density, 4),
                    "heading_count": policy.signals.heading_count,
                    "vector_grid_hits": policy.signals.vector_grid_hits,
                    "decomposition_confidence": round(policy.signals.decomposition_confidence, 4),
                    "fragmentation_risk": round(policy.signals.fragmentation_risk, 4),
                },
                **merge_diag,
                **layout_extract_diag,
                **layout_diag,
                "native_word_count": len(page.words),
                "native_table_count": len(page.table_blocks),
                "vector_count": len(page.vector_items),
                "fallback_used": bool(merged_page.metadata.get("fallback")),
                "unresolved_decisions": [] if (policy.provider_path != "native_only" or policy.use_lightweight_layout) else ["native_only_no_escalation"],
            }
        )
    provider_status["layout_lightweight"]["available"] = lightweight_success_count > 0

    used_docling = any(row.get("provider_path") != "native_only" for row in page_diags)
    used_lightweight = any(bool(row.get("lightweight_layout_used")) for row in page_diags)
    diagnostics = {
        "enabled": True,
        "used": True,
        "winner": "pdf_native_docling_layout" if used_lightweight else ("pdf_native_docling" if used_docling else "pdf_native"),
        "reason": "pdf_native_first_with_policy",
        "provider_status": provider_status,
        "pages": page_diags,
    }
    return tuple(final_pages), diagnostics
