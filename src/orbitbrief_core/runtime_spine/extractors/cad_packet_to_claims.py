from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
import importlib
import os
import re
from typing import Any, Mapping

from .narrative_claim_ontology import EvidenceRef, EvidenceRefSet, ExtractionDiagnostic, InternalClaim

_CAD_PACKET_TO_CLAIM: dict[str, str] = {
    "drawing_metadata_packet": "drawing_metadata_claim",
    "site_identity_packet": "site_location_claim",
    "network_room_or_closet_packet": "network_room_claim",
    "equipment_reference_packet": "equipment_reference_claim",
    "note_scope_packet": "scope_note_claim",
    "revision_change_packet": "revision_change_claim",
    "topology_hint_packet": "topology_hint_claim",
    "constructability_packet": "constructability_claim",
}
_CAD_ASSIST_PACKET_FAMILIES = frozenset({"note_scope_packet", "constructability_packet", "revision_change_packet"})
_CAD_METADATA_NOISE_RE = re.compile(
    r"\b(?:sheet\s*number|sheet\s*title|title\s*block|schedule|legend|details?|not\s*to\s*scale|scale\s*[:=])\b",
    flags=re.IGNORECASE,
)
_CAD_NETWORK_ROOM_RE = re.compile(r"\b(?:MDF|IDF|TR|TELECOM(?:MUNICATIONS)?\s*ROOM|CLOSET|ROOM\s*[A-Z0-9\-]+)\b", flags=re.IGNORECASE)
_CAD_EQUIPMENT_RE = re.compile(r"\b(?:AP|WAP|CCTV|PATCH\s*PANEL|SWITCH|RJ45|CAT6A?|SC\s*CONNECTOR|PORT)\b", flags=re.IGNORECASE)
_CAD_DISTANCE_RE = re.compile(r"\b\d+(?:\.\d+)?\s?(?:ft|feet|')\b", flags=re.IGNORECASE)
_CAD_AFF_RE = re.compile(r"\b\d+[\"']?\s?AFF\b", flags=re.IGNORECASE)
_CAD_SLACK_RE = re.compile(r"\b(?:\d+[\"']|\d+'\s*-\s*\d+[\"']?)\b")
_CAD_ROUTING_RE = re.compile(r"\b(?:run\s+to|homerun\s+to|terminate\s+at|nearest\s+IDF)\b", flags=re.IGNORECASE)
_CAD_TOPOLOGY_RE = re.compile(r"\b(?:MDF|IDF|TR|CLOSET)\b.*\b(?:to|->|toward|feeds?|serves)\b.*\b(?:MDF|IDF|TR|CLOSET)\b", flags=re.IGNORECASE)

_CAD_ROW_PRIORITIZED_KINDS = frozenset({"room_label", "closet_label", "equipment_label", "note_block", "callout", "dimension_text", "visual_region"})
_CAD_ROW_DEPRIORITIZED_KINDS = frozenset({"title_block", "title_block_field", "sheet_ref", "revision_block", "legend", "symbol_table", "table"})


def _enabled(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _load_backend(dotted_path: str | None):
    path = str(dotted_path or "").strip()
    if not path:
        return None
    module_name, _, attr = path.partition(":")
    if not module_name or not attr:
        return None
    try:
        module = importlib.import_module(module_name)
        backend = getattr(module, attr)
    except Exception:
        return None
    return backend if callable(backend) else None


def _assist_timeout_ms() -> int:
    try:
        value = int(str(os.getenv("ORBITBRIEF_QWEN_CAD_PACKET_ASSIST_TIMEOUT_MS", "450")).strip())
    except Exception:
        value = 450
    return max(50, value)


def _assist_confidence_threshold() -> float:
    try:
        value = float(str(os.getenv("ORBITBRIEF_QWEN_CAD_PACKET_ASSIST_CONFIDENCE", "0.68")).strip())
    except Exception:
        value = 0.68
    return max(0.0, min(1.0, value))


def _as_tuple_of_str(value: Any) -> tuple[str, ...]:
    if isinstance(value, tuple):
        return tuple(str(item) for item in value if str(item))
    if isinstance(value, list):
        return tuple(str(item) for item in value if str(item))
    return ()


def _packet_metadata(packet: Mapping[str, Any]) -> Mapping[str, Any]:
    metadata = packet.get("metadata", {})
    return metadata if isinstance(metadata, Mapping) else {}


def _packet_diag(packet: Mapping[str, Any]) -> Mapping[str, Any]:
    metadata = _packet_metadata(packet)
    diag = metadata.get("packet_diagnostic", {})
    return diag if isinstance(diag, Mapping) else {}


def _span_rows(packet: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    rows = packet.get("evidence_rows")
    if isinstance(rows, list):
        return tuple(item for item in rows if isinstance(item, Mapping))
    rows = _packet_metadata(packet).get("evidence_rows")
    if isinstance(rows, list):
        return tuple(item for item in rows if isinstance(item, Mapping))
    return ()


def _claim_id(packet_id: str, claim_family: str, primary_span_id: str) -> str:
    return f"claim:{packet_id}:{claim_family}:{primary_span_id}"


def _build_evidence(packet: Mapping[str, Any], primary_span_id: str | None = None) -> EvidenceRefSet | None:
    span_ids = _as_tuple_of_str(packet.get("span_ids", ()))
    packet_id = str(packet.get("packet_id", "packet:unknown"))
    selected_primary = primary_span_id or str(packet.get("primary_span_id") or "").strip() or None
    if selected_primary and selected_primary not in span_ids:
        span_ids = (selected_primary, *span_ids)
    if not selected_primary and span_ids:
        selected_primary = span_ids[0]
    if not selected_primary or not span_ids:
        return None
    supporting = tuple(span_id for span_id in span_ids if span_id != selected_primary)
    refs = (EvidenceRef(span_id=selected_primary, role="anchor"),) + tuple(
        EvidenceRef(span_id=span_id, role="support") for span_id in supporting
    )
    return EvidenceRefSet(
        packet_id=packet_id,
        primary_span_id=selected_primary,
        supporting_span_ids=supporting,
        all_span_ids=span_ids,
        refs=refs,
    )


def _derive_status(*, confidence: float, packet_state: str, uncertainty_markers: tuple[str, ...]) -> tuple[str, bool, bool]:
    if packet_state == "parked":
        return ("needs_review", True, True)
    if packet_state == "review_required" or uncertainty_markers:
        if confidence < 0.42:
            return ("needs_review", True, True)
        return ("ambiguous", True, False)
    if confidence >= 0.74:
        return ("asserted", False, False)
    if confidence >= 0.56:
        return ("possible", False, False)
    return ("ambiguous", True, False)


def _shorten(text: str, *, limit: int = 140) -> str:
    compact = re.sub(r"\s+", " ", text).strip().strip(" -:;,.")
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


def _row_kind(row: Mapping[str, Any]) -> str:
    metadata = row.get("metadata")
    if not isinstance(metadata, Mapping):
        return ""
    return str(metadata.get("kind") or metadata.get("region_kind") or "").strip().lower()


def _row_page_index(row: Mapping[str, Any]) -> int | None:
    metadata = row.get("metadata")
    if not isinstance(metadata, Mapping):
        return None
    raw = metadata.get("page_index")
    if isinstance(raw, int):
        return raw
    page_ref = metadata.get("page_ref")
    if isinstance(page_ref, Mapping) and isinstance(page_ref.get("page_index"), int):
        return int(page_ref.get("page_index"))
    return None


def _row_text(row: Mapping[str, Any]) -> str:
    return str(row.get("text") or row.get("normalized_text") or "").strip()


def _symbol_dictionary(rows: tuple[Mapping[str, Any], ...]) -> set[str]:
    symbols: set[str] = set()
    for row in rows:
        kind = _row_kind(row)
        text = _row_text(row)
        if kind in {"legend", "symbol_table"} or "symbol" in text.lower():
            for token in ("AP", "WAP", "CCTV", "RJ45", "CAT6", "CAT6A", "SC", "SWITCH", "PATCH PANEL"):
                if token.lower() in text.lower():
                    symbols.add(token.lower())
    return symbols


def _row_rank_score(
    row: Mapping[str, Any],
    *,
    packet_family: str,
    anchor_page: int | None,
    repeated_labels: Mapping[str, int],
    symbols: set[str],
) -> float:
    text = _row_text(row)
    if not text:
        return -10.0
    lower = text.lower()
    kind = _row_kind(row)
    score = 0.0

    if kind in _CAD_ROW_PRIORITIZED_KINDS:
        score += 0.7
    if kind in _CAD_ROW_DEPRIORITIZED_KINDS:
        score -= 1.2
    if packet_family != "drawing_metadata_packet" and _CAD_METADATA_NOISE_RE.search(lower):
        score -= 2.2
    if packet_family == "drawing_metadata_packet" and _CAD_METADATA_NOISE_RE.search(lower):
        score += 0.8

    page_index = _row_page_index(row)
    if anchor_page is not None and page_index is not None:
        score += 0.35 if page_index == anchor_page else -0.45

    label_key = re.sub(r"\s+", " ", lower).strip()
    if repeated_labels.get(label_key, 0) >= 2:
        score += 0.35

    metadata = row.get("metadata")
    if isinstance(metadata, Mapping):
        if bool(metadata.get("near_symbol")):
            score += 0.5
        symbol_distance = metadata.get("symbol_distance")
        try:
            if symbol_distance is not None:
                dist = float(symbol_distance)
                if dist <= 0.2:
                    score += 0.45
                elif dist <= 0.4:
                    score += 0.2
        except (TypeError, ValueError):
            pass
        if str(metadata.get("region_scope") or "").lower() == "floorplan":
            score += 0.3
        if str(metadata.get("cad_region_zone") or "").lower() in {"body", "floorplan", "plan_body"}:
            score += 0.25

    if symbols and any(token in lower for token in symbols):
        score += 0.25

    if packet_family == "network_room_or_closet_packet":
        if _CAD_NETWORK_ROOM_RE.search(text):
            score += 2.0
        if _CAD_EQUIPMENT_RE.search(text):
            score += 0.2
    elif packet_family == "equipment_reference_packet":
        if _CAD_EQUIPMENT_RE.search(text):
            score += 2.0
        if _CAD_NETWORK_ROOM_RE.search(text):
            score += 0.25
    elif packet_family in {"constructability_packet", "note_scope_packet", "topology_hint_packet"}:
        if _CAD_DISTANCE_RE.search(text):
            score += 1.2
        if _CAD_AFF_RE.search(text):
            score += 1.2
        if _CAD_SLACK_RE.search(text):
            score += 0.8
        if _CAD_ROUTING_RE.search(text):
            score += 1.2
        if _CAD_TOPOLOGY_RE.search(text):
            score += 1.3
    return score


def _extract_dense_facts(text: str) -> tuple[str, ...]:
    facts: list[str] = []
    for regex in (_CAD_DISTANCE_RE, _CAD_AFF_RE, _CAD_SLACK_RE, _CAD_ROUTING_RE, _CAD_EQUIPMENT_RE):
        for match in regex.finditer(text):
            token = _shorten(match.group(0), limit=48)
            if token and token not in facts:
                facts.append(token)
            if len(facts) >= 6:
                return tuple(facts)
    topo = _CAD_TOPOLOGY_RE.search(text)
    if topo:
        token = _shorten(topo.group(0), limit=64)
        if token and token not in facts:
            facts.append(token)
    return tuple(facts)


def _best_row_text(packet: Mapping[str, Any], *, packet_family: str, fallback: str = "") -> tuple[str, str | None]:
    primary_span_id = str(packet.get("primary_span_id") or "").strip()
    rows = _span_rows(packet)
    if not rows:
        return (_shorten(fallback), None) if fallback else ("", None)
    label_counts: dict[str, int] = {}
    for row in rows:
        row_key = re.sub(r"\s+", " ", _row_text(row).lower()).strip()
        if not row_key:
            continue
        label_counts[row_key] = label_counts.get(row_key, 0) + 1
    symbols = _symbol_dictionary(rows)
    anchor_page = None
    if primary_span_id:
        for row in rows:
            if str(row.get("span_id", "")).strip() == primary_span_id:
                anchor_page = _row_page_index(row)
                break
    ranked = sorted(
        rows,
        key=lambda row: (
            _row_rank_score(
                row,
                packet_family=packet_family,
                anchor_page=anchor_page,
                repeated_labels=label_counts,
                symbols=symbols,
            )
            + (
                0.75
                if str(row.get("span_id", "")).strip() == primary_span_id
                and packet_family in {"drawing_metadata_packet", "site_identity_packet", "note_scope_packet", "constructability_packet", "revision_change_packet", "topology_hint_packet"}
                else (
                    0.15
                    if str(row.get("span_id", "")).strip() == primary_span_id
                    else 0.0
                )
            ),
            str(row.get("span_id") or ""),
        ),
        reverse=True,
    )
    preferred = ranked[0]
    text = _row_text(preferred)
    if not text:
        text = fallback
    dense_facts = _extract_dense_facts(text)
    if dense_facts and packet_family in {"constructability_packet", "note_scope_packet", "equipment_reference_packet", "topology_hint_packet"}:
        text = f"{_shorten(text, limit=130)} | facts: {', '.join(dense_facts)}"
    return (_shorten(text, limit=180), str(preferred.get("span_id", "")).strip() or None)


def _normalized_body(packet: Mapping[str, Any], packet_family: str) -> tuple[str, str | None]:
    metadata = _packet_metadata(packet)
    cad_diag = metadata.get("cad_packetizer", {})
    fallback = ""
    if isinstance(cad_diag, Mapping):
        anchor_kind = str(cad_diag.get("anchor_kind", "")).strip()
        if anchor_kind:
            fallback = f"{packet_family.replace('_packet', '')} anchor: {anchor_kind}"
    text, source_span_id = _best_row_text(packet, packet_family=packet_family, fallback=fallback)
    lower = text.lower()
    if packet_family == "drawing_metadata_packet":
        if "sheet number" in lower or "sheet title" in lower or "revision" in lower:
            return (_shorten(text), source_span_id)
        return (_shorten(f"drawing metadata: {text}"), source_span_id)
    if packet_family == "site_identity_packet":
        return (_shorten(re.sub(r"^(?:site|location)\s*[:\-]\s*", "", text, flags=re.IGNORECASE)), source_span_id)
    if packet_family == "network_room_or_closet_packet":
        return (_shorten(re.sub(r"^(?:room|closet)\s*[:\-]\s*", "", text, flags=re.IGNORECASE)), source_span_id)
    if packet_family == "equipment_reference_packet":
        return (_shorten(re.sub(r"^(?:equipment)\s*[:\-]\s*", "", text, flags=re.IGNORECASE)), source_span_id)
    if packet_family == "note_scope_packet":
        return (_shorten(re.sub(r"^(?:note\s*\d*\s*[:\-]\s*)", "", text, flags=re.IGNORECASE)), source_span_id)
    if packet_family == "revision_change_packet":
        return (_shorten(re.sub(r"^(?:rev(?:ision)?\s*[a-z0-9]*\s*[:\-]\s*)", "", text, flags=re.IGNORECASE)), source_span_id)
    if packet_family == "topology_hint_packet":
        return (_shorten(text), source_span_id)
    if packet_family == "constructability_packet":
        return (_shorten(text), source_span_id)
    return (_shorten(text), source_span_id)


def _target_hint(claim_family: str) -> str:
    mapping = {
        "drawing_metadata_claim": "drawing_packet_metadata",
        "site_location_claim": "site_locations",
        "network_room_claim": "site_profile_from_drawings",
        "equipment_reference_claim": "known_quantities",
        "scope_note_claim": "scope_included",
        "constructability_claim": "access_and_logistics",
        "revision_change_claim": "deliverables_required",
        "topology_hint_claim": "site_profile_from_drawings",
    }
    return mapping.get(claim_family, "")


def _assist_request(packet: Mapping[str, Any], *, packet_family: str, claim_family: str, candidate_body: str) -> dict[str, Any]:
    rows = _span_rows(packet)
    primary_span_id = str(packet.get("primary_span_id") or "").strip()
    primary_text = ""
    supports: list[str] = []
    for row in rows:
        text = str(row.get("text") or row.get("normalized_text") or "").strip()
        if not text:
            continue
        clipped = _shorten(text, limit=220)
        if primary_span_id and str(row.get("span_id") or "").strip() == primary_span_id and not primary_text:
            primary_text = clipped
            continue
        supports.append(clipped)
    if not primary_text and rows:
        fallback = str(rows[0].get("text") or rows[0].get("normalized_text") or "").strip()
        primary_text = _shorten(fallback, limit=220)
    return {
        "packet_id": str(packet.get("packet_id") or "packet:unknown"),
        "packet_family": packet_family,
        "claim_family": claim_family,
        "candidate_body": _shorten(candidate_body, limit=220),
        "primary_text": primary_text,
        "support_texts": supports[:5],
        "target_field_hint": _target_hint(claim_family),
    }


def _maybe_assist_claim_body(packet: Mapping[str, Any], *, packet_family: str, claim_family: str, candidate_body: str) -> tuple[str, Mapping[str, Any], ExtractionDiagnostic | None]:
    if packet_family not in _CAD_ASSIST_PACKET_FAMILIES:
        return candidate_body, {"attempted": False, "reason": "unsupported_packet_family"}, None
    if not _enabled(os.getenv("ORBITBRIEF_ENABLE_QWEN_CAD_PACKET_ASSIST")):
        return candidate_body, {"attempted": False, "reason": "disabled"}, None
    backend = _load_backend(os.getenv("ORBITBRIEF_QWEN_CAD_PACKET_ASSIST_BACKEND"))
    if backend is None:
        return (
            candidate_body,
            {"attempted": True, "applied": False, "reason": "backend_unavailable"},
            ExtractionDiagnostic(
                code="cad_packet_assist_abstained",
                message="CAD packet-local model assist unavailable; deterministic body retained.",
                packet_id=str(packet.get("packet_id") or "packet:unknown"),
                metadata={"reason": "backend_unavailable", "packet_family": packet_family},
            ),
        )
    payload = _assist_request(packet, packet_family=packet_family, claim_family=claim_family, candidate_body=candidate_body)
    timeout_s = float(_assist_timeout_ms()) / 1000.0
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(backend, payload)
            raw = future.result(timeout=max(0.05, timeout_s))
    except FuturesTimeoutError:
        return (
            candidate_body,
            {"attempted": True, "applied": False, "reason": "backend_timeout"},
            ExtractionDiagnostic(
                code="cad_packet_assist_timeout",
                message="CAD packet-local model assist timed out; deterministic body retained.",
                packet_id=str(packet.get("packet_id") or "packet:unknown"),
                metadata={"packet_family": packet_family},
            ),
        )
    except Exception:
        return (
            candidate_body,
            {"attempted": True, "applied": False, "reason": "backend_error"},
            ExtractionDiagnostic(
                code="cad_packet_assist_error",
                message="CAD packet-local model assist failed; deterministic body retained.",
                packet_id=str(packet.get("packet_id") or "packet:unknown"),
                metadata={"packet_family": packet_family},
            ),
        )
    if raw is None:
        return (
            candidate_body,
            {"attempted": True, "applied": False, "reason": "backend_abstained"},
            ExtractionDiagnostic(
                code="cad_packet_assist_abstained",
                message="CAD packet-local model assist abstained; deterministic body retained.",
                packet_id=str(packet.get("packet_id") or "packet:unknown"),
                metadata={"packet_family": packet_family},
            ),
        )

    body: str = ""
    confidence = 1.0
    model_name = "qwen:cad_packet_assist"
    if isinstance(raw, str):
        body = raw
    elif isinstance(raw, Mapping):
        body = str(raw.get("normalized_body") or raw.get("claim_body") or raw.get("body") or raw.get("suggestion") or "")
        try:
            confidence = float(raw.get("confidence", 1.0) or 1.0)
        except Exception:
            confidence = 1.0
        model_name = str(raw.get("model_name") or model_name)
    cleaned = _shorten(body, limit=160)
    threshold = _assist_confidence_threshold()
    if not cleaned or confidence < threshold:
        reason = "low_confidence" if confidence < threshold else "empty_body"
        return (
            candidate_body,
            {"attempted": True, "applied": False, "reason": reason, "confidence": confidence, "threshold": threshold},
            ExtractionDiagnostic(
                code="cad_packet_assist_abstained",
                message="CAD packet-local model assist returned weak output; deterministic body retained.",
                packet_id=str(packet.get("packet_id") or "packet:unknown"),
                metadata={"packet_family": packet_family, "reason": reason},
            ),
        )
    return (
        cleaned,
        {
            "attempted": True,
            "applied": True,
            "reason": "applied",
            "confidence": max(0.0, min(1.0, confidence)),
            "threshold": threshold,
            "model_name": model_name,
        },
        ExtractionDiagnostic(
            code="cad_packet_assist_applied",
            message="CAD packet-local model assist provided bounded claim-body normalization.",
            packet_id=str(packet.get("packet_id") or "packet:unknown"),
            metadata={"packet_family": packet_family, "model_name": model_name},
        ),
    )


def extract_cad_claims_from_packet(packet: Mapping[str, Any], context: Any) -> tuple[tuple[InternalClaim, ...], tuple[ExtractionDiagnostic, ...]]:
    metadata = _packet_metadata(packet)
    packet_family = str(metadata.get("packet_family", "")).strip()
    packet_id = str(packet.get("packet_id", "packet:unknown"))
    claim_family = _CAD_PACKET_TO_CLAIM.get(packet_family)
    if not claim_family:
        return (
            (),
            (
                ExtractionDiagnostic(
                    code="cad_packet_family_not_supported",
                    message="CAD packet family is not supported by bounded CAD extractor.",
                    packet_id=packet_id,
                    metadata={"packet_family": packet_family},
                ),
            ),
        )
    packet_confidence = float(packet.get("confidence", 0.0) or 0.0)
    packet_state = str(metadata.get("packet_state", "")).strip().lower() or "extract"
    uncertainty_markers = _as_tuple_of_str(metadata.get("uncertainty_markers", ()))
    claim_body, source_span_id = _normalized_body(packet, packet_family)
    claim_body, assist_metadata, assist_diagnostic = _maybe_assist_claim_body(
        packet,
        packet_family=packet_family,
        claim_family=claim_family,
        candidate_body=claim_body,
    )
    if not claim_body:
        return (
            (),
            (
                ExtractionDiagnostic(
                    code="cad_claim_body_empty",
                    message="CAD packet did not provide bounded local text for claim body.",
                    packet_id=packet_id,
                    metadata={"packet_family": packet_family},
                ),
            ),
        )
    evidence = _build_evidence(packet, primary_span_id=source_span_id)
    if evidence is None:
        return (
            (),
            (
                ExtractionDiagnostic(
                    code="packet_missing_evidence",
                    message="CAD packet lacks evidence span ids and cannot emit a claim.",
                    packet_id=packet_id,
                    metadata={"packet_family": packet_family},
                ),
            ),
        )
    status, verification_needed, stronger_source_needed = _derive_status(
        confidence=packet_confidence,
        packet_state=packet_state,
        uncertainty_markers=uncertainty_markers,
    )
    claim = InternalClaim(
        claim_id=_claim_id(packet_id, claim_family, evidence.primary_span_id),
        claim_family=claim_family,  # type: ignore[arg-type]
        packet_id=packet_id,
        packet_family=packet_family,
        claim_body=claim_body,
        confidence=max(0.0, min(1.0, packet_confidence)),
        status=status,  # type: ignore[arg-type]
        verification_needed=verification_needed,
        stronger_source_needed=stronger_source_needed,
        evidence=evidence,
        metadata={
            "role_id": str(getattr(context, "role_id", "")),
            "modality": str(getattr(context, "modality", "")),
            "uncertainty_markers": list(uncertainty_markers),
            "packet_state": packet_state,
            "target_field_hint": _target_hint(claim_family),
            "projection_hint": _target_hint(claim_family),
            "packet_diagnostics": dict(_packet_diag(packet)),
            "packet_local_model_assist": dict(assist_metadata),
            "verification_flags": ["packet_state_review"] if packet_state != "extract" else [],
            "review_flags": [marker for marker in uncertainty_markers if marker in {"parked", "review_required", "noise_regions_suppressed", "family_conflict"}],
        },
    )
    diagnostic = ExtractionDiagnostic(
        code="cad_claim_extracted",
        message="CAD packet emitted bounded internal claim.",
        packet_id=packet_id,
        metadata={
            "packet_family": packet_family,
            "claim_family": claim_family,
            "source_span_id": evidence.primary_span_id,
            "packet_state": packet_state,
        },
    )
    diagnostics: tuple[ExtractionDiagnostic, ...]
    if assist_diagnostic is None:
        diagnostics = (diagnostic,)
    else:
        diagnostics = (assist_diagnostic, diagnostic)
    return ((claim,), diagnostics)

