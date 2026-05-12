from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from orbitbrief_core.parser.adapters.docx_common import StructuredDocxBlock, StructuredDocxHypothesis


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\x00", " ").split()).strip()


def _safe_get(obj: Any, *names: str) -> Any:
    for name in names:
        if isinstance(obj, Mapping) and name in obj:
            return obj[name]
        if hasattr(obj, name):
            return getattr(obj, name)
    return None


def _iter_nodes(value: Any) -> list[Any]:
    collected: list[Any] = []
    stack = [value]
    seen: set[int] = set()
    while stack:
        current = stack.pop()
        oid = id(current)
        if oid in seen:
            continue
        seen.add(oid)
        collected.append(current)
        if isinstance(current, Mapping):
            for child in current.values():
                if isinstance(child, (Mapping, list, tuple)):
                    stack.append(child)
            continue
        if isinstance(current, (list, tuple)):
            for child in current:
                if isinstance(child, (Mapping, list, tuple)) or hasattr(child, "__dict__"):
                    stack.append(child)
            continue
        for attr in ("children", "items", "blocks", "elements"):
            child = _safe_get(current, attr)
            if isinstance(child, (list, tuple)):
                stack.append(child)
    return collected


def _role(label: str | None, text: str) -> str:
    hint = (label or "").strip().lower()
    if "head" in hint or hint in {"title", "section_title"}:
        return "heading"
    if "table" in hint:
        return "table_row"
    if "list" in hint or "bullet" in hint:
        return "bullet"
    if text.startswith(("-", "*", "•")):
        return "bullet"
    return "paragraph"


def extract_docx_structured_hypothesis(*, docx_path: Path | None = None, docx_bytes: bytes | None = None) -> StructuredDocxHypothesis | None:
    """Alternate structured DOCX provider hypothesis (Docling-backed when available)."""
    # Current provider path needs a local file path.
    if docx_path is None or not docx_path.exists():
        return None
    try:
        from docling.document_converter import DocumentConverter  # type: ignore
    except Exception:
        return None
    try:
        converter = DocumentConverter()
        result = converter.convert(str(docx_path))
    except Exception:
        return None

    document = _safe_get(result, "document")
    if document is None:
        return None

    root = None
    for exporter in ("export_to_dict", "to_dict"):
        method = _safe_get(document, exporter)
        if callable(method):
            try:
                root = method()
                break
            except Exception:
                root = None
    seed = root if root is not None else document
    blocks: list[StructuredDocxBlock] = []
    index = 0
    for node in _iter_nodes(seed):
        label = _safe_get(node, "label", "type", "kind", "category", "name")
        label_text = str(label).strip().lower() if label is not None else ""
        text = _clean_text(_safe_get(node, "text", "content", "value", "markdown"))
        if not text:
            continue
        role = _role(label_text or None, text)
        style_name = str(_safe_get(node, "style", "style_name") or "") or None
        heading_level_raw = _safe_get(node, "heading_level", "level", "outline_level")
        heading_level = int(heading_level_raw) if isinstance(heading_level_raw, int) else (1 if role == "heading" else None)
        list_level_raw = _safe_get(node, "list_level", "indent_level")
        list_level = int(list_level_raw) if isinstance(list_level_raw, int) else (1 if role == "bullet" else None)
        table_group_id = None
        if role == "table_row":
            table_raw = _safe_get(node, "table_id", "table_group_id")
            if isinstance(table_raw, str) and table_raw.strip():
                table_group_id = table_raw.strip()
            else:
                table_group_id = "table:alternate:0000"
        section_hint = None
        lower = text.lower()
        for hint in ("assumption", "risk", "deliverable", "open question", "note", "action"):
            if hint in lower:
                section_hint = hint.replace(" ", "_")
                break
        blocks.append(
            StructuredDocxBlock(
                block_id=f"docx_alt_block:{index:04d}",
                text=text,
                role=role,
                style_name=style_name,
                heading_level=heading_level,
                list_level=list_level,
                table_group_id=table_group_id,
                section_hint=section_hint,
                confidence=0.76 if role != "heading" else 0.84,
                source="alternate_structured",
                metadata={"provider": "docx_structured", "docling_label": label_text or "unknown"},
            )
        )
        index += 1

    if not blocks:
        return None
    return StructuredDocxHypothesis(
        hypothesis_id="hypothesis:docx_structured",
        source="alternate_structured",
        blocks=tuple(blocks),
        confidence=0.79,
        metadata={"provider": "docx_structured", "block_count": len(blocks)},
    )
