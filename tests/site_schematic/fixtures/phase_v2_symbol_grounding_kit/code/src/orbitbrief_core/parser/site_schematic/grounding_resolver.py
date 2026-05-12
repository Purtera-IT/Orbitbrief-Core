from __future__ import annotations

from typing import Iterable, List

from orbitbrief_core.parser.site_schematic.legend_grounding_models import GroundedSymbol, LegendGroundingEntry
from orbitbrief_core.parser.site_schematic.symbol_candidate_grouping import SymbolCandidateGroup

def resolve_grounded_symbols(
    *,
    candidates: Iterable[SymbolCandidateGroup],
    legend_dictionary: Iterable[LegendGroundingEntry],
) -> List[GroundedSymbol]:
    legend_dictionary = list(legend_dictionary)
    out: List[GroundedSymbol] = []

    for cand in candidates:
        best = None
        best_score = -1.0
        for entry in legend_dictionary:
            score = 0.0
            if entry.family in cand.family_candidates:
                score += 1.0
            for hint in cand.text_hints:
                if hint and hint.lower() in (entry.raw_label or "").lower():
                    score += 0.5
            if score > best_score:
                best = entry
                best_score = score

        if best is None:
            out.append(GroundedSymbol(
                grounded_id=f"grounded:{cand.candidate_id}",
                page_index=cand.page_index,
                candidate_id=cand.candidate_id,
                family="unknown_symbol_group",
                semantic_meaning="unresolved",
                bbox=cand.bbox,
                confidence=0.2,
                status="unresolved",
            ))
            continue

        status = "grounded" if best_score >= 1.0 and best.family != "unknown_symbol_group" else "ambiguous"
        out.append(GroundedSymbol(
            grounded_id=f"grounded:{cand.candidate_id}",
            page_index=cand.page_index,
            candidate_id=cand.candidate_id,
            family=best.family,
            semantic_meaning=best.raw_label or best.family,
            bbox=cand.bbox,
            legend_ids=[best.legend_id],
            supporting_text_hints=cand.text_hints,
            confidence=min(0.95, 0.5 + 0.2 * best_score),
            status=status,
            metadata={"family_candidates": cand.family_candidates},
        ))
    return out
