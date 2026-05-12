from __future__ import annotations

import io
import re
import shutil
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any


_SHEET_ROW_RE = re.compile(r"^T\d{3}\b")
_SECTION_KEYWORDS = {
    "SCOPE",
    "GUIDELINES",
    "NOTES",
    "REQUIREMENTS",
    "DOCUMENTATION",
    "INDEX",
    "DRAWING",
    "GENERAL",
    "INFRASTRUCTURE",
    "INSTALLATION",
    "FIRESTOPPING",
    "SECURITY",
    "TELECOMMUNICATIONS",
}


@dataclass(frozen=True, slots=True)
class DetectedPageSection:
    section_id: str
    page_index: int
    order_index: int
    title: str
    bbox: tuple[float, float, float, float] | None
    content_lines: tuple[str, ...]
    confidence: float
    metadata: dict[str, Any]


def _group_words_into_lines(words: list[tuple[float, float, float, float, str]]) -> list[tuple[float, float, str]]:
    lines: dict[float, list[tuple[float, float, str]]] = {}
    for x0, y0, x1, _, text in words:
        key = round(y0 / 3.0) * 3.0
        lines.setdefault(key, []).append((x0, x1, text))
    out: list[tuple[float, float, str]] = []
    for y_key in sorted(lines):
        chunks = sorted(lines[y_key], key=lambda row: row[0])
        # Split into separate line segments when horizontal gap indicates another column block.
        segments: list[list[tuple[float, float, str]]] = []
        current: list[tuple[float, float, str]] = []
        last_x1 = -1.0
        for x0, x1, token in chunks:
            gap = x0 - last_x1 if last_x1 >= 0 else 0.0
            if current and gap > 26.0:
                segments.append(current)
                current = []
            current.append((x0, x1, token))
            last_x1 = max(last_x1, x1)
        if current:
            segments.append(current)
        for segment in segments:
            text = " ".join(str(token).strip() for _, _, token in segment if str(token).strip())
            text = " ".join(text.split()).strip()
            if text:
                out.append((y_key, segment[0][0], text))
    return out


def _extract_word_rows(page: Any) -> list[tuple[float, float, float, float, str]]:
    rows = []
    try:
        words = page.get_text("words") or []
    except Exception:
        words = []
    for row in words:
        if len(row) < 5:
            continue
        x0, y0, x1, y1, text = row[:5]
        text = str(text).strip()
        if not text:
            continue
        rows.append((float(x0), float(y0), float(x1), float(y1), text))
    return rows


def _rect_iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0 = max(ax0, bx0)
    iy0 = max(ay0, by0)
    ix1 = min(ax1, bx1)
    iy1 = min(ay1, by1)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    area_a = max(1.0, (ax1 - ax0) * (ay1 - ay0))
    area_b = max(1.0, (bx1 - bx0) * (by1 - by0))
    return inter / (area_a + area_b - inter)


def _dedupe_rects(rects: list[tuple[float, float, float, float]]) -> list[tuple[float, float, float, float]]:
    out: list[tuple[float, float, float, float]] = []
    for rect in sorted(rects, key=lambda r: ((r[1], r[0], -(r[2] - r[0])))):
        if any(_rect_iou(rect, prior) >= 0.95 for prior in out):
            continue
        out.append(rect)
    return out


def _score_title_candidate(text: str) -> float:
    clean = " ".join(text.split()).strip().upper()
    if not clean:
        return -10.0
    tokens = clean.split()
    alpha_count = sum(1 for ch in clean if ch.isalpha())
    digit_count = sum(1 for ch in clean if ch.isdigit())
    keyword_hits = sum(1 for token in tokens if token in _SECTION_KEYWORDS)
    score = 0.0
    if re.match(r"^[A-Z]\b", clean):
        score += 5.0
    if keyword_hits:
        score += min(6.0, keyword_hits * 3.0)
    if 2 <= len(tokens) <= 10:
        score += 2.0
    if alpha_count >= 6:
        score += 1.5
    if digit_count > alpha_count:
        score -= 4.0
    if re.match(r"^[0-9]", clean):
        score -= 3.0
    return score


def _canonicalize_title(text: str) -> str:
    raw_tokens = [re.sub(r"[^A-Z0-9/&-]", "", tok.upper()) for tok in text.split()]
    tokens = [tok for tok in raw_tokens if tok]
    if not tokens:
        return ""
    keyword_idx = next((i for i, tok in enumerate(tokens) if tok in _SECTION_KEYWORDS), -1)
    if keyword_idx >= 0:
        lead_idx = keyword_idx
        for i in range(max(0, keyword_idx - 2), keyword_idx):
            if re.fullmatch(r"[A-Z]", tokens[i]):
                lead_idx = i
                break
        start = lead_idx
        end = min(len(tokens), keyword_idx + 4)
        tokens = tokens[start:end]
    if len(tokens) > 6:
        tokens = tokens[:6]
    return " ".join(tokens).strip()


def _is_heading_line(text: str) -> bool:
    clean = " ".join((text or "").split()).strip().upper()
    if not clean:
        return False
    if len(clean) < 4 or len(clean) > 80:
        return False
    if clean.startswith(("(", "•", "-", "*")):
        return False
    if clean.count(" ") > 8:
        return False
    if " SHALL " in f" {clean} ":
        return False
    if re.match(r"^[A-Z]\.?\s+[A-Z0-9]", clean):
        return True
    if any(token in clean.split() for token in _SECTION_KEYWORDS):
        return True
    return False


def _grid_title_from_line(text: str) -> str:
    clean = " ".join((text or "").split()).strip().upper()
    if not clean:
        return ""
    letters = re.findall(r"\b([A-Z])\b", clean)
    if len(letters) < 3:
        return ""
    if not re.search(r"\b\d+\.", clean):
        return ""
    uniq: list[str] = []
    for letter in letters:
        if letter not in uniq:
            uniq.append(letter)
    if len(uniq) < 3:
        return ""
    ordered = sorted(uniq)
    return f"{ordered[0]}-{ordered[-1]} INDEX GRID"


def _sections_from_heading_lines(
    *,
    page_index: int,
    words: list[tuple[float, float, float, float, str]],
    lines_all: list[tuple[float, float, str]],
    page_w: float,
) -> list[DetectedPageSection]:
    if not lines_all:
        return []
    heading_positions: list[int] = []
    for idx, (_, _, text) in enumerate(lines_all):
        if _is_heading_line(text):
            heading_positions.append(idx)
    if not heading_positions:
        return []
    sections: list[DetectedPageSection] = []
    for order, start_idx in enumerate(heading_positions, start=1):
        end_idx = heading_positions[order] if order < len(heading_positions) else len(lines_all)
        y0 = lines_all[start_idx][0]
        y1 = lines_all[end_idx - 1][0] + 14.0 if end_idx > start_idx else y0 + 14.0
        if y1 <= y0:
            continue
        in_range_words = [row for row in words if row[1] >= y0 - 2.0 and row[3] <= y1 + 6.0]
        if not in_range_words:
            continue
        title = _canonicalize_title(lines_all[start_idx][2])
        if len(title) < 3:
            continue
        x0 = min(row[0] for row in in_range_words)
        x1 = max(row[2] for row in in_range_words)
        x0 = max(0.0, x0 - 4.0)
        x1 = min(page_w, x1 + 4.0)
        section_lines = tuple(line[2] for line in lines_all[start_idx:end_idx] if line[2])
        sections.append(
            DetectedPageSection(
                section_id=f"section:p{page_index}:line:{order:03d}",
                page_index=page_index,
                order_index=order,
                title=title,
                bbox=(x0, y0 - 2.0, x1, y1 + 4.0),
                content_lines=section_lines,
                confidence=0.68,
                metadata={"detector": "heading_line_fallback", "box_indicator": True, "box_role": "inferred_text_block"},
            )
        )
    return sections


def _sections_from_column_blocks(
    *,
    page_index: int,
    words: list[tuple[float, float, float, float, str]],
    lines_all: list[tuple[float, float, str]],
    page_w: float,
    max_sections_per_page: int,
) -> list[DetectedPageSection]:
    if not lines_all:
        return []
    threshold = max(26.0, page_w * 0.045)
    clusters: list[dict[str, Any]] = []
    for idx, (_, x0, _) in enumerate(lines_all):
        placed = False
        for cluster in clusters:
            centroid = float(cluster["x_sum"]) / max(1, int(cluster["count"]))
            if abs(x0 - centroid) <= threshold:
                cluster["line_indices"].append(idx)
                cluster["x_sum"] += x0
                cluster["count"] += 1
                placed = True
                break
        if not placed:
            clusters.append({"line_indices": [idx], "x_sum": x0, "count": 1})

    sections: list[DetectedPageSection] = []
    order = 0
    for cluster in sorted(clusters, key=lambda c: float(c["x_sum"]) / max(1, int(c["count"]))):
        line_indices = sorted(cluster["line_indices"], key=lambda idx: lines_all[idx][0])
        if len(line_indices) < 3:
            continue
        block_start = 0
        for i in range(1, len(line_indices) + 1):
            split = False
            if i == len(line_indices):
                split = True
            else:
                y_prev = lines_all[line_indices[i - 1]][0]
                y_cur = lines_all[line_indices[i]][0]
                if (y_cur - y_prev) > 22.0:
                    split = True
            if not split:
                continue
            block_idxs = line_indices[block_start:i]
            block_start = i
            if len(block_idxs) < 3:
                continue
            block_lines = [lines_all[idx][2] for idx in block_idxs if lines_all[idx][2]]
            if not block_lines:
                continue
            y0 = lines_all[block_idxs[0]][0]
            y1 = lines_all[block_idxs[-1]][0] + 14.0
            in_range_words = [row for row in words if row[1] >= y0 - 2.0 and row[3] <= y1 + 5.0]
            if not in_range_words:
                continue
            x0 = max(0.0, min(row[0] for row in in_range_words) - 3.0)
            x1 = min(page_w, max(row[2] for row in in_range_words) + 3.0)
            width = max(1.0, x1 - x0)
            grid_title = next((grid for grid in (_grid_title_from_line(line) for line in block_lines[:14]) if grid), "")
            title_candidates = block_lines[:10]
            best_title_line = max(title_candidates, key=_score_title_candidate)
            best_score = _score_title_candidate(best_title_line)
            role = (
                "sidebar_annotation"
                if (x0 >= page_w * 0.62 or (x0 >= page_w * 0.55 and width <= page_w * 0.35))
                else "text_block"
            )
            if role == "text_block" and not grid_title:
                continue
            min_score = 1.6 if role == "sidebar_annotation" else 2.8
            if best_score < min_score and not grid_title:
                continue
            title = grid_title or _canonicalize_title(best_title_line)
            if len(title) < 3:
                continue
            if not grid_title and role == "text_block":
                title_tokens = set(title.split())
                if "NOTES" not in title_tokens and not (title_tokens & _SECTION_KEYWORDS):
                    continue
            order += 1
            confidence = 0.74 if grid_title else (0.72 if role == "sidebar_annotation" else 0.66)
            sections.append(
                DetectedPageSection(
                    section_id=f"section:p{page_index}:col:{order:03d}",
                    page_index=page_index,
                    order_index=order,
                    title=title,
                    bbox=(x0, y0 - 2.0, x1, y1 + 4.0),
                    content_lines=tuple(block_lines),
                    confidence=confidence,
                    metadata={
                        "detector": "column_block_layout",
                        "box_indicator": True,
                        "box_role": "alpha_index_grid" if grid_title else role,
                    },
                )
            )
            if len(sections) >= max_sections_per_page:
                break
        if len(sections) >= max_sections_per_page:
            break
    return sections


def _sections_from_alpha_grid_rows(
    *,
    page_index: int,
    words: list[tuple[float, float, float, float, str]],
    lines_all: list[tuple[float, float, str]],
    page_w: float,
    max_sections_per_page: int,
) -> list[DetectedPageSection]:
    sections: list[DetectedPageSection] = []
    order = 0
    for idx, (y, _, text) in enumerate(lines_all):
        title = _grid_title_from_line(text)
        if not title:
            continue
        start_idx = max(0, idx - 2)
        end_idx = min(len(lines_all), idx + 8)
        block_lines = [line[2] for line in lines_all[start_idx:end_idx] if line[2]]
        if len(block_lines) < 2:
            continue
        y0 = lines_all[start_idx][0]
        y1 = lines_all[end_idx - 1][0] + 14.0
        in_range_words = [row for row in words if row[1] >= y0 - 2.0 and row[3] <= y1 + 5.0]
        if not in_range_words:
            continue
        x0 = max(0.0, min(row[0] for row in in_range_words) - 3.0)
        x1 = min(page_w, max(row[2] for row in in_range_words) + 3.0)
        order += 1
        sections.append(
            DetectedPageSection(
                section_id=f"section:p{page_index}:alpha_grid:{order:03d}",
                page_index=page_index,
                order_index=order,
                title=title,
                bbox=(x0, y0 - 2.0, x1, y1 + 4.0),
                content_lines=tuple(block_lines),
                confidence=0.78,
                metadata={"detector": "alpha_grid_row", "box_indicator": True, "box_role": "alpha_index_grid"},
            )
        )
        if len(sections) >= max_sections_per_page:
            break
    return sections


def _ocr_lines_from_clip(
    *,
    page: Any,
    bbox: tuple[float, float, float, float],
) -> list[str]:
    try:
        import fitz  # type: ignore
        import pytesseract  # type: ignore
        from PIL import Image  # type: ignore
    except Exception:
        return []
    if shutil.which("tesseract") is None:
        return []
    clip = fitz.Rect(*bbox)
    if clip.width <= 1.0 or clip.height <= 1.0:
        return []
    try:
        pix = page.get_pixmap(matrix=fitz.Matrix(3.0, 3.0), clip=clip, alpha=False)
        image = Image.open(io.BytesIO(pix.tobytes("png")))
        data = pytesseract.image_to_data(
            image,
            output_type=pytesseract.Output.DICT,
            config="--psm 6",
        )
    except Exception:
        return []
    lines: dict[tuple[int, int, int], list[str]] = {}
    conf_sum: dict[tuple[int, int, int], float] = {}
    conf_count: dict[tuple[int, int, int], int] = {}
    for i, txt in enumerate(data.get("text", [])):
        text = str(txt or "").strip()
        if not text:
            continue
        try:
            conf = float(data.get("conf", ["-1"])[i])
        except Exception:
            conf = -1.0
        if conf < 32.0:
            continue
        key = (
            int(data.get("block_num", [0])[i]),
            int(data.get("par_num", [0])[i]),
            int(data.get("line_num", [0])[i]),
        )
        lines.setdefault(key, []).append(text)
        conf_sum[key] = conf_sum.get(key, 0.0) + conf
        conf_count[key] = conf_count.get(key, 0) + 1
    out: list[tuple[tuple[int, int, int], float, str]] = []
    for key in sorted(lines):
        text = " ".join(lines[key]).strip()
        text = " ".join(text.split())
        if not text:
            continue
        avg_conf = conf_sum.get(key, 0.0) / max(1, conf_count.get(key, 0))
        if avg_conf < 38.0:
            continue
        if len(text) > 90:
            continue
        out.append((key, avg_conf, text))
    # De-duplicate by normalized line value while preserving order.
    seen: set[str] = set()
    deduped: list[str] = []
    for _, _, text in out:
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(text)
    return deduped


def _sidebar_annotation_section(
    *,
    page_index: int,
    words: list[tuple[float, float, float, float, str]],
    lines_all: list[tuple[float, float, str]],
    page_w: float,
    sidebar_rects: list[tuple[float, float, float, float]] | None = None,
    sidebar_ocr_lines: list[str] | None = None,
) -> DetectedPageSection | None:
    sidebar_lines = [row for row in lines_all if row[1] >= page_w * 0.78 and len(row[2].strip()) >= 4]
    if len(sidebar_lines) < 4:
        return None
    titleblock_cues = {
        "PROJECT",
        "SHEET",
        "TITLE",
        "DATE",
        "NO",
        "REVISIONS",
        "ISSUED",
        "CONSTRUCTION",
        "CLIENT",
        "ARCHITECT",
        "CONSULTANT",
        "T000",
    }
    strict_keep_cues = {"PROJECT", "SHEET", "TITLE", "DATE", "NO", "T000", "NOTES", "REVISIONS", "ISSUED", "CONSTRUCTION"}
    reject_tokens = {
        "SHALL",
        "MUST",
        "INSTALL",
        "INSTALLATION",
        "CABLE",
        "CONTRACTOR",
        "OUTLET",
        "CONDUIT",
        "FIBER",
        "RACK",
        "IDF",
        "MDF",
        "PATCH",
        "GROUNDING",
        "RISER",
        "GUIDELINES",
        "MATERIALS",
        "CONSISTING",
        "WARRANTY",
        "MAINTENANCE",
        "REQUIRED",
        "SERVICE",
        "FIRE",
    }
    normalized: list[tuple[float, float, str, list[str]]] = []
    for y, x, text in sidebar_lines:
        clean = " ".join(text.split()).strip()
        if not clean:
            continue
        tokens = [tok.strip(".,:;()").upper() for tok in clean.split() if tok.strip(".,:;()")]
        normalized.append((y, x, clean, tokens))
    if not normalized:
        return None

    # Geometry-first path: if right-side titleblock cell rectangles are available,
    # collect text strictly inside those cells to reduce spill from main body notes.
    if sidebar_rects:
        rect_lines: list[tuple[float, float, str]] = []
        for x0, y0, x1, y1 in sorted(sidebar_rects, key=lambda r: (r[1], r[0])):
            in_rect_words = [
                row
                for row in words
                if row[0] >= x0 - 1.5 and row[2] <= x1 + 1.5 and row[1] >= y0 - 1.5 and row[3] <= y1 + 1.5
            ]
            if not in_rect_words:
                continue
            for ly, lx, ltext in _group_words_into_lines(in_rect_words):
                clean = " ".join(ltext.split()).strip()
                if not clean:
                    continue
                if len(clean) > 88:
                    continue
                rect_lines.append((ly, lx, clean))
        # Include top strip metadata lines near title block that might not be inside a cell.
        top_meta_lines = [row for row in lines_all if row[1] >= page_w * 0.82 and row[0] <= 220.0 and len(row[2].strip()) >= 3]
        merged_rect_lines = sorted([*rect_lines, *top_meta_lines], key=lambda r: (r[0], r[1]))
        if merged_rect_lines:
            deduped: list[tuple[float, float, str]] = []
            seen = set()
            for y, x, text in merged_rect_lines:
                clean = " ".join(text.split()).strip()
                if not clean:
                    continue
                tokens = [tok.strip(".,:;()").upper() for tok in clean.split() if tok.strip(".,:;()")]
                if not tokens:
                    continue
                cue_hit = any(tok in strict_keep_cues for tok in tokens)
                date_or_sheet = bool(re.search(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", clean)) or bool(re.search(r"\bT\d{3}\b", clean))
                reject_hit = any(tok in reject_tokens for tok in tokens)
                shortish = len(tokens) <= 4 and len(clean) <= 42
                if "ARE/ARE" in clean.upper():
                    continue
                if reject_hit:
                    continue
                if cue_hit and len(tokens) > 8 and "SEAL DATE SHEET" not in " ".join(tokens):
                    continue
                if not (cue_hit or date_or_sheet or (shortish and x >= page_w * 0.87)):
                    continue
                key = clean.lower()
                if key in seen:
                    continue
                seen.add(key)
                deduped.append((y, x, clean))
            if len(deduped) < 6:
                # If OCR/text quality is weak in sidebar cells, keep a minimal fallback sample.
                deduped = []
                seen = set()
                for y, x, text in merged_rect_lines[:40]:
                    clean = " ".join(text.split()).strip()
                    if not clean:
                        continue
                    key = clean.lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    deduped.append((y, x, clean))
            sx0 = min(r[0] for r in sidebar_rects)
            sy0 = min(r[1] for r in sidebar_rects)
            sx1 = max(r[2] for r in sidebar_rects)
            sy1 = max(r[3] for r in sidebar_rects)
            ocr_lines = [line.strip() for line in (sidebar_ocr_lines or []) if line.strip()]
            if ocr_lines:
                ocr_keep: list[str] = []
                ocr_seen: set[str] = set()
                ocr_cue_hits = 0
                for line in ocr_lines:
                    clean = " ".join(line.split()).strip()
                    if not clean:
                        continue
                    tokens = [tok.strip(".,:;()").upper() for tok in clean.split() if tok.strip(".,:;()")]
                    if not tokens:
                        continue
                    cue_hit = any(tok in strict_keep_cues for tok in tokens)
                    reject_hit = any(tok in reject_tokens for tok in tokens)
                    has_addr = bool(re.search(r"\b\d{3,5}\b", clean))
                    if cue_hit or bool(re.search(r"\bT\d{3}\b", clean)) or bool(re.search(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", clean)):
                        ocr_cue_hits += 1
                    if reject_hit and not cue_hit:
                        continue
                    if len(clean) > 120:
                        continue
                    if not (cue_hit or has_addr or len(tokens) <= 6):
                        continue
                    key = clean.lower()
                    if key in ocr_seen:
                        continue
                    ocr_seen.add(key)
                    ocr_keep.append(clean)
                if ocr_keep and ocr_cue_hits >= 3:
                    deduped = [(float(idx), sx0, line) for idx, line in enumerate(ocr_keep, start=1)]
            if top_meta_lines:
                sy0 = min(sy0, min(row[0] for row in top_meta_lines) - 2.0)
            return DetectedPageSection(
                section_id=f"section:p{page_index}:sidebar_annotations",
                page_index=page_index,
                order_index=0,
                title="SIDEBAR ANNOTATIONS",
                bbox=(sx0, max(0.0, sy0 - 2.0), sx1, sy1 + 4.0),
                content_lines=tuple(row[2] for row in deduped[:180]),
                confidence=0.8,
                metadata={
                    "detector": "sidebar_rect_cells",
                    "box_indicator": True,
                    "box_role": "sidebar_annotation",
                    "cell_count": len(sidebar_rects),
                },
            )

    seed_indices: set[int] = set()
    for idx, (_, _, clean, tokens) in enumerate(normalized):
        if not tokens:
            continue
        cue_hit = any(tok in titleblock_cues for tok in tokens)
        date_or_sheet = bool(re.search(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", clean)) or bool(re.search(r"\bT\d{3}\b", clean))
        company_like = any(tok in {"SUITE", "GA", "INC", "LLC", "ROSWELL", "ALPHARETTA", "ARCHITECT", "CONSULTANT", "CLIENT"} for tok in tokens)
        if cue_hit or date_or_sheet or company_like:
            seed_indices.add(idx)

    expanded: set[int] = set()
    for idx in sorted(seed_indices):
        for j in range(max(0, idx - 1), min(len(normalized), idx + 2)):
            expanded.add(j)

    filtered_lines: list[tuple[float, float, str]] = []
    for idx in sorted(expanded):
        y, x, clean, tokens = normalized[idx]
        if not tokens:
            continue
        cue_hit = any(tok in titleblock_cues for tok in tokens)
        strict_cue_hit = any(tok in strict_keep_cues for tok in tokens)
        reject_hit = any(tok in reject_tokens for tok in tokens)
        shortish = len(tokens) <= 9 and len(clean) <= 80
        if x < page_w * 0.83 and not cue_hit:
            continue
        if reject_hit:
            continue
        if not shortish and not cue_hit:
            continue
        if cue_hit and not strict_cue_hit and len(tokens) > 6:
            continue
        filtered_lines.append((y, x, clean))
    if len(filtered_lines) < 8:
        filtered_lines = [(y, x, " ".join(text.split()).strip()) for y, x, text in sidebar_lines[:80]]
    y0 = filtered_lines[0][0]
    y1 = filtered_lines[-1][0] + 14.0
    in_range_words = [row for row in words if row[0] >= page_w * 0.78 and row[1] >= y0 - 2.0 and row[3] <= y1 + 5.0]
    if not in_range_words:
        return None
    x0 = max(0.0, min(row[0] for row in in_range_words) - 3.0)
    x1 = min(page_w, max(row[2] for row in in_range_words) + 3.0)
    ordered = tuple(row[2] for row in filtered_lines[:120])
    return DetectedPageSection(
        section_id=f"section:p{page_index}:sidebar_annotations",
        page_index=page_index,
        order_index=0,
        title="SIDEBAR ANNOTATIONS",
        bbox=(x0, y0 - 2.0, x1, y1 + 4.0),
        content_lines=ordered,
        confidence=0.74,
        metadata={"detector": "sidebar_column", "box_indicator": True, "box_role": "sidebar_annotation"},
    )


def detect_page_sections_from_pdf(
    *,
    pdf_path: Path,
    page_index: int,
    max_sections_per_page: int = 40,
) -> list[DetectedPageSection]:
    try:
        import fitz  # type: ignore
    except Exception:
        return []

    if not pdf_path.exists():
        return []

    try:
        doc = fitz.open(pdf_path)
    except Exception:
        return []
    try:
        if page_index < 1 or page_index > len(doc):
            return []
        page = doc[page_index - 1]
        words = _extract_word_rows(page)
        if not words:
            return []

        page_h = float(page.rect.height)
        page_w = float(page.rect.width)
        raw_rects: list[tuple[float, float, float, float]] = []
        try:
            drawings = page.get_drawings() or []
        except Exception:
            drawings = []
        for row in drawings:
            rect = row.get("rect")
            if rect is None:
                continue
            x0 = float(rect.x0)
            y0 = float(rect.y0)
            x1 = float(rect.x1)
            y1 = float(rect.y1)
            w = x1 - x0
            h = y1 - y0
            if w < 95.0 or h < 120.0:
                continue
            if w > page_w * 0.9 and h > page_h * 0.9:
                continue
            if y0 < 100.0:
                continue
            if y1 > page_h - 120.0:
                continue
            raw_rects.append((x0, y0, x1, y1))
        box_rects = _dedupe_rects(raw_rects)[: max_sections_per_page * 3]
        sidebar_rects = _dedupe_rects(
            [
                (float(row.get("rect").x0), float(row.get("rect").y0), float(row.get("rect").x1), float(row.get("rect").y1))
                for row in drawings
                if row.get("rect") is not None
                and float(row.get("rect").x0) >= page_w * 0.70
                and 18.0 <= float(row.get("rect").width) <= page_w * 0.28
                and 40.0 <= float(row.get("rect").height) <= page_h * 0.22
            ]
        )[:120]

        sections: list[DetectedPageSection] = []
        for idx, bbox in enumerate(sorted(box_rects, key=lambda r: (r[1], r[0]))[:max_sections_per_page], start=1):
            x0, y0, x1, y1 = bbox
            title_band_words = [
                row
                for row in words
                if row[0] >= x0 + 4.0 and row[2] <= x1 - 4.0 and row[1] >= y0 - 2.0 and row[3] <= min(y1, y0 + 52.0)
            ]
            title_lines = _group_words_into_lines(title_band_words)
            in_box_words = [row for row in words if row[0] >= x0 and row[2] <= x1 and row[1] >= y0 and row[3] <= y1]
            box_lines = _group_words_into_lines(in_box_words)
            title_candidates = [line[2] for line in title_lines[:3]]
            title_candidates.extend(line[2] for line in box_lines[:10])
            raw_title = ""
            if title_candidates:
                raw_title = max(title_candidates, key=_score_title_candidate)
            clean_title = _canonicalize_title(raw_title)
            if len(clean_title) < 3:
                continue
            if len(clean_title.split()) > 12:
                continue
            letter_candidates = [
                row[4].upper()
                for row in words
                if row[0] >= x0 and row[0] <= x0 + 70.0 and row[1] >= y0 - 2.0 and row[1] <= y0 + 70.0 and re.fullmatch(r"[A-Z]", row[4])
            ]
            section_letter = letter_candidates[0] if letter_candidates else ""
            if section_letter and not clean_title.startswith(f"{section_letter} "):
                clean_title = f"{section_letter} {clean_title}".strip()
            line_texts = tuple(line[2] for line in box_lines if line[2])
            keyword_hit = any(token in clean_title.split() for token in _SECTION_KEYWORDS)
            if not keyword_hit and not re.match(r"^[A-Z]\s+[A-Z]{2,}", clean_title):
                continue
            confidence = 0.9 if keyword_hit else 0.76
            sections.append(
                DetectedPageSection(
                    section_id=f"section:p{page_index}:{idx:03d}",
                    page_index=page_index,
                    order_index=idx,
                    title=clean_title,
                    bbox=bbox,
                    content_lines=line_texts,
                    confidence=confidence,
                    metadata={"detector": "vector_box_layout", "box_indicator": True, "box_role": "section_box"},
                )
            )

        lines_all = _group_words_into_lines(words)
        column_sections = _sections_from_column_blocks(
            page_index=page_index,
            words=words,
            lines_all=lines_all,
            page_w=page_w,
            max_sections_per_page=max_sections_per_page,
        )
        if sections:
            existing_boxes = [row.bbox for row in sections if row.bbox is not None]
            for candidate in column_sections:
                if candidate.bbox is None:
                    continue
                if any(_rect_iou(candidate.bbox, prior) >= 0.7 for prior in existing_boxes):
                    continue
                sections.append(candidate)
                existing_boxes.append(candidate.bbox)
                if len(sections) >= max_sections_per_page:
                    break
        else:
            sections = column_sections

        alpha_grid_sections = _sections_from_alpha_grid_rows(
            page_index=page_index,
            words=words,
            lines_all=lines_all,
            page_w=page_w,
            max_sections_per_page=max_sections_per_page,
        )
        if alpha_grid_sections:
            existing = [row.bbox for row in sections if row.bbox is not None]
            for candidate in alpha_grid_sections:
                if candidate.bbox is None:
                    continue
                if any(_rect_iou(candidate.bbox, prior) >= 0.7 for prior in existing):
                    continue
                sections.append(candidate)
                existing.append(candidate.bbox)
                if len(sections) >= max_sections_per_page:
                    break

        sidebar_section = _sidebar_annotation_section(
            page_index=page_index,
            words=words,
            lines_all=lines_all,
            page_w=page_w,
            sidebar_rects=sidebar_rects,
            sidebar_ocr_lines=_ocr_lines_from_clip(
                page=page,
                bbox=(
                    min((r[0] for r in sidebar_rects), default=page_w * 0.78),
                    min((r[1] for r in sidebar_rects), default=0.0),
                    max((r[2] for r in sidebar_rects), default=page_w),
                    max((r[3] for r in sidebar_rects), default=page_h),
                ),
            ),
        )
        if sidebar_section is not None and sidebar_section.bbox is not None:
            existing = [row.bbox for row in sections if row.bbox is not None]
            if not any(_rect_iou(sidebar_section.bbox, prior) >= 0.75 for prior in existing):
                sections.append(sidebar_section)

        # Fallback for pages where vector boxes are not explicitly drawn.
        if not sections:
            sections = _sections_from_heading_lines(
                page_index=page_index,
                words=words,
                lines_all=lines_all,
                page_w=page_w,
            )

        # Add drawing index section if we can detect it from lines.
        drawing_title_idx = next((i for i, (_, _, text) in enumerate(lines_all) if "DRAWING INDEX" in text.upper()), -1)
        if drawing_title_idx >= 0:
            drawing_lines = []
            for _, _, text in lines_all[drawing_title_idx + 1 :]:
                if _SHEET_ROW_RE.match(text.strip()):
                    drawing_lines.append(text.strip())
                elif drawing_lines and not text.strip():
                    break
            sections.append(
                DetectedPageSection(
                    section_id=f"section:p{page_index}:drawing_index",
                    page_index=page_index,
                    order_index=len(sections) + 1,
                    title="DRAWING INDEX",
                    bbox=None,
                    content_lines=tuple(drawing_lines),
                    confidence=0.9 if drawing_lines else 0.7,
                    metadata={"detector": "line_text", "row_count": len(drawing_lines), "box_indicator": False, "box_role": "drawing_index"},
                )
            )
        ordered = sorted(
            sections,
            key=lambda row: (
                9e9 if row.bbox is None else row.bbox[1],
                9e9 if row.bbox is None else row.bbox[0],
                row.order_index,
            ),
        )
        return list(
            replace(row, order_index=idx)
            for idx, row in enumerate(ordered, start=1)
        )
    finally:
        doc.close()

