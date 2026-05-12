from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

BBox = tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class SymbolCandidateGroup:
    candidate_id: str
    page_index: int
    bbox: BBox | None
    primitive_ids: tuple[str, ...] = ()
    text_hints: tuple[str, ...] = ()
    family_candidates: tuple[str, ...] = ()
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


_ALIAS_TOKEN_RE = re.compile(r"^[A-Z][A-Z0-9/-]{0,10}$")
_ALIAS_FAMILY_HINTS: dict[str, tuple[str, ...]] = {
    "AP": ("ap_wap_marker", "wireless_access_point"),
    "WAP": ("ap_wap_marker", "wireless_access_point"),
    "CAM": ("camera_device",),
    "CCTV": ("camera_device",),
    "CR": ("card_reader_device",),
    "DC": ("door_contact_marker",),
    "INT": ("intercom_endpoint",),
    "INTERCOM": ("intercom_endpoint",),
    "WIRELESS": ("wireless_access_point",),
    "TEL": ("wall_phone_marker",),
    "PHONE": ("telecom_voice_outlet",),
    "VOICE": ("telecom_voice_outlet",),
    "TV": ("av_endpoint_marker",),
    "ZN": ("zigbee_node_outlet",),
    "ZIGBEE": ("zigbee_node_outlet",),
    "PP": ("patch_panel_row",),
    "RACK": ("telecom_rack_front",),
    "JB": ("junction_box",),
    "JBOX": ("junction_box",),
    "TGB": ("telecommunications_ground_busbar",),
    "TMGB": ("telecommunications_ground_busbar",),
    "DC": ("door_contact", "door_contact_marker"),
    "B": ("telephone_outlet",),
    "E": ("telephone_outlet",),
}


def _alias_tokens(text_hints: tuple[str, ...]) -> tuple[str, ...]:
    out: list[str] = []
    for token in text_hints:
        raw = str(token).strip().upper().strip("()[]{}.,:;")
        if not raw:
            continue
        if _ALIAS_TOKEN_RE.match(raw):
            out.append(raw)
    deduped: list[str] = []
    seen: set[str] = set()
    for token in out:
        if token in seen:
            continue
        seen.add(token)
        deduped.append(token)
    return tuple(deduped[:24])


def _merge_family_candidates(
    *,
    primitive_kind: str | None,
    alias_tokens: tuple[str, ...],
) -> tuple[str, ...]:
    if primitive_kind == "box":
        base = ["telecom_rack_front", "pull_or_junction_box", "patch_panel_row"]
    elif primitive_kind == "line":
        base = ["conduit_pathway", "riser_endpoint", "unknown_symbol_group"]
    elif primitive_kind == "polyline":
        base = ["ladder_rack_runway", "conduit_pathway", "unknown_symbol_group"]
    else:
        base = ["unknown_symbol_group"]
    hinted: list[str] = []
    for token in alias_tokens:
        hinted.extend(_ALIAS_FAMILY_HINTS.get(token, ()))
    merged: list[str] = []
    for family in [*hinted, *base]:
        if family not in merged:
            merged.append(family)
    return tuple(merged)


def group_symbol_candidates_from_primitives(
    *,
    page_index: int,
    vector_primitives: list[Any],
    nearby_text_hints: list[str] | None = None,
) -> list[SymbolCandidateGroup]:
    out: list[SymbolCandidateGroup] = []
    # Keep broader local context so packet alias mappings can see later-page tokens
    # (e.g., INT/JB/TGB/CAM schedule tokens that may appear after early title text).
    text_hints = tuple((nearby_text_hints or [])[:140])
    alias_tokens = _alias_tokens(text_hints)
    for idx, primitive in enumerate(vector_primitives):
        bbox = getattr(primitive, "bbox", None) if not isinstance(primitive, dict) else primitive.get("bbox")
        primitive_id = getattr(primitive, "primitive_id", None) if not isinstance(primitive, dict) else primitive.get("primitive_id")
        primitive_kind = getattr(primitive, "primitive_kind", None) if not isinstance(primitive, dict) else primitive.get("primitive_kind")
        if bbox is None or primitive_id is None:
            continue
        family_candidates = _merge_family_candidates(primitive_kind=primitive_kind, alias_tokens=alias_tokens)
        out.append(
            SymbolCandidateGroup(
                candidate_id=f"cand:{page_index}:{idx}",
                page_index=page_index,
                bbox=bbox,
                primitive_ids=(primitive_id,),
                text_hints=text_hints,
                family_candidates=family_candidates,
                confidence=0.55,
                metadata={"seed_kind": primitive_kind, "alias_tokens": alias_tokens},
            )
        )
    return out
