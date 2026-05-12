from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


def _spec_path() -> Path:
    return Path(__file__).with_name("vocabulary_spec.json")


@lru_cache(maxsize=1)
def load_universal_symbol_vocabulary() -> dict[str, Any]:
    return json.loads(_spec_path().read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def vocabulary_class_lookup() -> dict[str, dict[str, Any]]:
    spec = load_universal_symbol_vocabulary()
    rows = spec.get("classes", [])
    return {str(row["id"]): dict(row) for row in rows if isinstance(row, dict) and "id" in row}


def packet_focus_class_ids(packet_id: str) -> tuple[str, ...]:
    spec = load_universal_symbol_vocabulary()
    focus = spec.get("packet_focus_sets", {})
    if not isinstance(focus, dict):
        return ()
    values = focus.get(packet_id, ())
    if not isinstance(values, list):
        return ()
    return tuple(str(row) for row in values)


def _normalized_context(
    *,
    local_text: str,
    legend_texts: tuple[str, ...],
    note_clauses: tuple[str, ...],
    abbreviations: tuple[str, ...],
) -> str:
    rows = [local_text, *legend_texts, *note_clauses, *abbreviations]
    return " ".join((row or "").lower() for row in rows)


def infer_vocabulary_matches(
    *,
    local_text: str,
    legend_texts: tuple[str, ...],
    note_clauses: tuple[str, ...],
    abbreviations: tuple[str, ...],
    top_k: int = 6,
) -> tuple[dict[str, Any], ...]:
    lookup = vocabulary_class_lookup()
    context = _normalized_context(
        local_text=local_text,
        legend_texts=legend_texts,
        note_clauses=note_clauses,
        abbreviations=abbreviations,
    )
    scores: list[tuple[float, dict[str, Any]]] = []
    for row in lookup.values():
        keywords = row.get("keywords", [])
        if not isinstance(keywords, list):
            continue
        matched: list[str] = []
        score = 0.0
        for token in keywords:
            token = str(token).strip().lower()
            if not token:
                continue
            if token in context:
                matched.append(token)
                score += 1.0
                if len(token) >= 8:
                    score += 0.2
        if score <= 0.0:
            continue
        if row.get("training_plan") == "separate":
            score += 0.25
        scores.append(
            (
                score,
                {
                    "class_id": row["id"],
                    "class_name": row.get("name", ""),
                    "modality": row.get("modality", ""),
                    "tier1": row.get("tier1", ""),
                    "tier2": row.get("tier2", ""),
                    "roles": list(row.get("roles", [])),
                    "training_plan": row.get("training_plan", ""),
                    "merge_parent": row.get("merge_parent", ""),
                    "sparsity": row.get("sparsity", ""),
                    "matched_keywords": matched,
                    "score": round(score, 4),
                },
            )
        )
    scores.sort(key=lambda item: item[0], reverse=True)
    return tuple(row for _, row in scores[: max(1, top_k)])


def classify_candidate_with_vocabulary(
    *,
    packet_id: str,
    local_text: str,
    legend_texts: tuple[str, ...],
    note_clauses: tuple[str, ...],
    abbreviations: tuple[str, ...],
) -> dict[str, Any]:
    matches = infer_vocabulary_matches(
        local_text=local_text,
        legend_texts=legend_texts,
        note_clauses=note_clauses,
        abbreviations=abbreviations,
        top_k=8,
    )
    focus_classes = set(packet_focus_class_ids(packet_id))
    focus_matches = [row for row in matches if row["class_id"] in focus_classes]
    preferred = focus_matches[0] if focus_matches else (matches[0] if matches else None)
    return {
        "packet_id": packet_id,
        "focus_class_ids": sorted(focus_classes),
        "primary_class_id": preferred["class_id"] if preferred else "unknown",
        "primary_modality": preferred["modality"] if preferred else "unknown",
        "primary_tier1": preferred["tier1"] if preferred else "",
        "primary_tier2": preferred["tier2"] if preferred else "",
        "primary_training_plan": preferred["training_plan"] if preferred else "defer",
        "primary_merge_parent": preferred["merge_parent"] if preferred else "",
        "focus_matched": bool(preferred and preferred["class_id"] in focus_classes),
        "matches": [dict(row) for row in matches],
        "focus_matches": [dict(row) for row in focus_matches],
    }

