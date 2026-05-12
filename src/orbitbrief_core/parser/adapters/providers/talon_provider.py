from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class TalonBoundarySuggestion:
    quoted_start: int | None = None
    signature_start: int | None = None
    confidence: float = 0.0
    metadata: Mapping[str, Any] = field(default_factory=dict)


def suggest_talon_boundaries(text: str) -> TalonBoundarySuggestion | None:
    """Best-effort Talon boundary hints for quote/signature extraction."""
    if not text.strip():
        return None
    try:
        from talon import quotations, signature  # type: ignore
    except Exception:
        return None

    quoted_start: int | None = None
    signature_start: int | None = None
    metadata: dict[str, Any] = {"provider": "talon"}

    try:
        # Talon keeps newest/current content in the return value.
        current_only = quotations.extract_from_plain(text)
        if isinstance(current_only, str) and current_only.strip():
            current_idx = text.find(current_only)
            if current_idx >= 0:
                candidate = current_idx + len(current_only)
                if candidate < len(text):
                    quoted_start = candidate
    except Exception:
        quoted_start = None

    try:
        # Extract signature from tail content.
        _sig_name, sig_text = signature.extract(text, sender=None)
        if isinstance(sig_text, str) and sig_text.strip():
            idx = text.find(sig_text)
            if idx >= 0:
                signature_start = idx
    except Exception:
        signature_start = None

    if quoted_start is None and signature_start is None:
        return None

    confidence = 0.78
    if quoted_start is not None and signature_start is not None:
        confidence = 0.84
    metadata["quoted_detected"] = quoted_start is not None
    metadata["signature_detected"] = signature_start is not None
    return TalonBoundarySuggestion(
        quoted_start=quoted_start,
        signature_start=signature_start,
        confidence=confidence,
        metadata=metadata,
    )
