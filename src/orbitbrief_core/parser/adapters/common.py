from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from orbitbrief_core.parser.router import ParsePlan, RouterInput
from orbitbrief_core.parser.shared.builders import DocumentParseBuilder
from orbitbrief_core.parser.shared.types import ReviewCategory, ReviewSeverity, SourceLayer


@dataclass(frozen=True, slots=True)
class AdapterContext:
    """Resolved runtime context passed into adapter-specific parsing code."""

    doc_id: str
    pack_id: str
    role_id: str
    modality: str
    source_layer: SourceLayer
    metadata: Mapping[str, Any] = field(default_factory=dict)


def _manifest_attr(compiled_pack: Any, name: str, default: str) -> str:
    manifest = getattr(compiled_pack, "manifest", None)
    value = getattr(manifest, name, None) if manifest is not None else None
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def resolve_modality(parse_plan: ParsePlan) -> str:
    modality = parse_plan.metadata.get("modality") if isinstance(parse_plan.metadata, Mapping) else None
    if modality:
        return str(modality)
    parser_profile_id = getattr(parse_plan, "parser_profile_id", "")
    if parser_profile_id and ":" in parser_profile_id:
        return parser_profile_id.rsplit(":", 1)[-1]
    return parse_plan.adapter_chain[0] if parse_plan.adapter_chain else "txt"


def build_context(
    *,
    router_input: RouterInput,
    parse_plan: ParsePlan,
    compiled_pack: Any,
    source_layer: SourceLayer | None = None,
) -> AdapterContext:
    return AdapterContext(
        doc_id=router_input.doc_id,
        pack_id=_manifest_attr(compiled_pack, "pack_id", "professional_services_text"),
        role_id=_manifest_attr(compiled_pack, "role_id", "transcript_or_notes"),
        modality=resolve_modality(parse_plan),
        source_layer=source_layer or SourceLayer.NORMALIZED,
        metadata={
            "parser_profile_id": parse_plan.parser_profile_id,
            "routing_confidence": parse_plan.routing_confidence,
            "strategy_chain": list(parse_plan.strategy_chain),
            "packet_policy": parse_plan.packet_policy,
        },
    )


def make_builder(
    *,
    router_input: RouterInput,
    parse_plan: ParsePlan,
    compiled_pack: Any,
    source_layer: SourceLayer | None = None,
) -> DocumentParseBuilder:
    ctx = build_context(
        router_input=router_input,
        parse_plan=parse_plan,
        compiled_pack=compiled_pack,
        source_layer=source_layer,
    )
    builder = DocumentParseBuilder(
        doc_id=ctx.doc_id,
        pack_id=ctx.pack_id,
        role_id=ctx.role_id,
        modality=ctx.modality,
        container_type=parse_plan.container_type,
        discourse_type=parse_plan.discourse_type,
        source_layer=ctx.source_layer,
    )
    builder.set_metadata(
        {
            "router_metadata": dict(parse_plan.metadata),
            "adapter_context": dict(ctx.metadata),
            "filename": router_input.filename,
            "mime_type": router_input.mime_type,
            "page_count": router_input.page_count,
            "router_review_flags": [getattr(flag, "flag_id", None) for flag in parse_plan.review_flags],
        }
    )
    return builder


_TEXT_KEYS = (
    "raw_text",
    "full_text",
    "text",
    "content",
    "body",
    "normalized_text",
)
_BYTES_KEYS = (
    "raw_bytes",
    "file_bytes",
    "content_bytes",
    "binary",
    "bytes",
)
_PATH_KEYS = (
    "path",
    "file_path",
    "source_path",
    "local_path",
)


def extract_path(router_input: RouterInput) -> Path | None:
    for key in _PATH_KEYS:
        value = router_input.metadata.get(key) if isinstance(router_input.metadata, Mapping) else None
        if not value:
            continue
        path = Path(str(value))
        if path.exists():
            return path
    if router_input.filename:
        path = Path(router_input.filename)
        if path.exists():
            return path
    return None


def extract_bytes(router_input: RouterInput) -> bytes | None:
    if isinstance(router_input.metadata, Mapping):
        for key in _BYTES_KEYS:
            value = router_input.metadata.get(key)
            if isinstance(value, bytes):
                return value
    path = extract_path(router_input)
    if path and path.is_file():
        try:
            return path.read_bytes()
        except Exception:
            return None
    return None


def extract_text(router_input: RouterInput, *, prefer_full_text: bool = True) -> str:
    if isinstance(router_input.metadata, Mapping):
        keys = _TEXT_KEYS if prefer_full_text else tuple(reversed(_TEXT_KEYS))
        for key in keys:
            value = router_input.metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value
            if isinstance(value, bytes):
                try:
                    text = value.decode("utf-8")
                except UnicodeDecodeError:
                    text = value.decode("utf-8", errors="replace")
                if text.strip():
                    return text
    path = extract_path(router_input)
    if path and path.suffix.lower() in {".txt", ".md", ".eml"}:
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            pass
    return router_input.raw_text_preview or ""


def add_flag(
    builder: DocumentParseBuilder,
    *,
    severity: ReviewSeverity,
    category: ReviewCategory,
    message: str,
    span_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> str:
    return builder.add_review_flag(
        severity=severity,
        category=category,
        message=message,
        span_id=span_id,
        metadata=metadata,
    )


def line_starts(text: str) -> tuple[int, ...]:
    starts = [0]
    for idx, ch in enumerate(text):
        if ch == "\n":
            starts.append(idx + 1)
    return tuple(starts)


def char_range_from_lines(starts: Sequence[int], start_line: int, end_line_exclusive: int, text: str) -> tuple[int, int]:
    if not starts:
        return (0, len(text))
    start = starts[start_line]
    if end_line_exclusive >= len(starts):
        end = len(text)
    else:
        end = starts[end_line_exclusive]
    return (start, end)


def score_to_authority(score: float, *, low: float = 0.35, medium: float = 0.65) -> str:
    if score < low:
        return "low"
    if score < medium:
        return "medium"
    return "high"
