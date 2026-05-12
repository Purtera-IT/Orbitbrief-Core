from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from orbitbrief_core.parser.adapters.base import AbstractAdapter, AdapterInfo
from orbitbrief_core.parser.adapters.common import add_flag, extract_bytes, extract_path, make_builder
from orbitbrief_core.parser.adapters.pdf_common import arbitrate_hypotheses, ocr_hypotheses
from orbitbrief_core.parser.adapters.pdf_page_judge import HardPageJudge, run_hard_page_judge
from orbitbrief_core.parser.adapters.providers.vl_embedding_provider import VLEmbeddingProvider, candidate_from_block
from orbitbrief_core.parser.graph.scorers.region_relevance import RegionRelevanceRequest, RegionRelevanceScoringService
from orbitbrief_core.parser.router import ParsePlan, RouterInput
from orbitbrief_core.parser.shared.types import PageRef, ReviewCategory, ReviewSeverity, SourceLayer


@dataclass(frozen=True, slots=True)
class PdfOcrParseConfig:
    attach_heading_spans: bool = True
    low_confidence_threshold: float = 0.58
    multimodal_region_relevance: bool = True
    hard_page_judge: bool = True


class PdfOcrAdapter(AbstractAdapter):
    info = AdapterInfo(
        name="PdfOcrAdapter",
        modality="pdf_ocr",
        description="OCR-sensitive PDF adapter with optional OCR/layout backends and arbitration.",
        optional_dependencies=("fitz", "pytesseract", "paddleocr", "mineru"),
    )

    def __init__(self, config: PdfOcrParseConfig | None = None) -> None:
        self._config = config or PdfOcrParseConfig()

    def parse(self, *, router_input: RouterInput, parse_plan: ParsePlan, compiled_pack: Any):
        source_layer = getattr(SourceLayer, "OCR", SourceLayer.NORMALIZED)
        builder = make_builder(router_input=router_input, parse_plan=parse_plan, compiled_pack=compiled_pack, source_layer=source_layer)
        pdf_path = extract_path(router_input)
        pdf_bytes = extract_bytes(router_input)
        hypotheses = ocr_hypotheses(pdf_path=pdf_path, pdf_bytes=pdf_bytes)
        arbitration = arbitrate_hypotheses(hypotheses)
        if self._config.hard_page_judge:
            arbitration, judge_decision = run_hard_page_judge(
                arbitration=arbitration,
                hypotheses=hypotheses,
                judge=HardPageJudge(available=False),
            )
            if judge_decision is not None:
                add_flag(
                    builder,
                    severity=ReviewSeverity.INFO,
                    category=ReviewCategory.AMBIGUITY,
                    message="Hard-page judge evaluated disputed OCR hypotheses.",
                    metadata={"adapter": "pdf_ocr", "abstained": judge_decision.abstained, "reason_codes": list(judge_decision.reason_codes)},
                )
        winner_hypothesis_id = str(arbitration.metadata.get("winner_hypothesis_id", "unknown"))
        winner_source = str(arbitration.metadata.get("winner", "unknown"))
        arbitration_reason_codes = tuple(str(code) for code in arbitration.metadata.get("arbitration_reason_codes", ()))

        root_section_id = builder.add_section(
            title="PDF_OCR",
            section_path=("PDF_OCR",),
            metadata={
                "synthetic": True,
                "adapter": "pdf_ocr",
                "winner_hypothesis_id": winner_hypothesis_id,
                "winner_source": winner_source,
                "arbitration_reason_codes": list(arbitration_reason_codes),
            },
        )
        builder.set_section_root(root_section_id)
        add_flag(
            builder,
            severity=ReviewSeverity.INFO,
            category=ReviewCategory.QUALITY,
            message="Artifact routed through OCR-sensitive PDF lane.",
            metadata={"adapter": "pdf_ocr", "hypothesis_sources": [h.source for h in hypotheses]},
        )

        if not hypotheses:
            add_flag(
                builder,
                severity=ReviewSeverity.WARNING,
                category=ReviewCategory.QUALITY,
                message="No OCR or layout hypothesis succeeded for PDF OCR lane.",
                metadata={"adapter": "pdf_ocr"},
            )
            return builder.build()

        for disagreement in arbitration.disagreements:
            add_flag(
                builder,
                severity=ReviewSeverity.INFO,
                category=ReviewCategory.AMBIGUITY,
                message=f"OCR arbitration disagreement: {disagreement}",
                metadata={"adapter": "pdf_ocr", "hypothesis_scores": dict(arbitration.hypothesis_scores)},
            )
        for reason_code in arbitration_reason_codes:
            if reason_code in {"weak_ocr", "low_confidence_ocr", "reading_order_uncertain"}:
                add_flag(
                    builder,
                    severity=ReviewSeverity.WARNING if reason_code != "reading_order_uncertain" else ReviewSeverity.INFO,
                    category=ReviewCategory.QUALITY if reason_code != "reading_order_uncertain" else ReviewCategory.AMBIGUITY,
                    message=f"OCR arbitration signal: {reason_code}",
                    metadata={"adapter": "pdf_ocr", "winner_source": winner_source},
                )
            if reason_code in {"heading_body_dispute", "section_boundary_dispute", "table_attachment_dispute"}:
                add_flag(
                    builder,
                    severity=ReviewSeverity.INFO,
                    category=ReviewCategory.AMBIGUITY,
                    message=f"OCR structure disputed: {reason_code}",
                    metadata={"adapter": "pdf_ocr", "winner_source": winner_source},
                )
        if arbitration.repeated_header_texts or arbitration.repeated_footer_texts:
            add_flag(
                builder,
                severity=ReviewSeverity.INFO,
                category=ReviewCategory.QUALITY,
                message="Repeated OCR header/footer text detected and demoted.",
                metadata={
                    "adapter": "pdf_ocr",
                    "headers": list(arbitration.repeated_header_texts),
                    "footers": list(arbitration.repeated_footer_texts),
                },
            )

        region_scores_by_block_id: dict[str, float] = {}
        if self._config.multimodal_region_relevance and {"table_attachment_dispute", "section_boundary_dispute", "reading_order_dispute"} & set(arbitration_reason_codes):
            provider = VLEmbeddingProvider(available=False)
            region_scorer = RegionRelevanceScoringService(backend=provider.score_region_relevance, threshold=0.75, max_fanout=2)
            grouped_by_page: dict[int, list] = {}
            for block in arbitration.selected_blocks:
                grouped_by_page.setdefault(block.page_index, []).append(block)
            for page_index, page_blocks in grouped_by_page.items():
                candidates = tuple(
                    candidate_from_block(
                        region_id=str(block.block_id),
                        page_index=block.page_index,
                        bbox=block.bbox,
                        text=block.text,
                    )
                    for block in page_blocks[:10]
                )
                query = " ".join(block.text for block in page_blocks[:2]).strip()
                if not query or not candidates:
                    continue
                relevance = region_scorer.score(
                    RegionRelevanceRequest(
                        page_index=page_index,
                        query_text=query,
                        candidate_regions=candidates,
                    )
                )
                for item in relevance:
                    if item.abstained or item.score is None:
                        continue
                    region_scores_by_block_id[item.region_id] = max(region_scores_by_block_id.get(item.region_id, 0.0), float(item.score))

        section_stack: list[tuple[int, str, tuple[str, ...]]] = [(0, root_section_id, ("PDF_OCR",))]
        section_name_counts: dict[tuple[str, ...], int] = {}
        chronology_rank = 0

        for block in arbitration.selected_blocks:
            if not block.text.strip():
                continue
            if block.role == "heading":
                title = self._unique_component(block.text, section_stack[-1][2], section_name_counts)
                parent_id, parent_path = section_stack[-1][1], section_stack[-1][2]
                section_path = parent_path + (title,)
                section_id = builder.add_section(
                    title=title,
                    section_path=section_path,
                    parent_section_id=parent_id,
                    metadata={
                        "adapter": "pdf_ocr",
                        "role": "heading",
                        **dict(block.metadata),
                        "source": block.source,
                        "winner_hypothesis_id": winner_hypothesis_id,
                        "winner_source": winner_source,
                    },
                )
                section_stack.append((1, section_id, section_path))
                if self._config.attach_heading_spans:
                    span_id = builder.add_span(
                        text=block.text,
                        normalized_text=block.text.lower(),
                        page_ref=PageRef(page_index=block.page_index),
                        bbox=block.bbox,
                        section_path=section_path,
                        chronology_rank=chronology_rank,
                        authority_score=min(0.82, max(0.35, block.confidence)),
                        source_layer=source_layer,
                        metadata={
                            "kind": "ocr_heading",
                            **dict(block.metadata),
                            "source": block.source,
                            "winner_hypothesis_id": winner_hypothesis_id,
                            "winner_source": winner_source,
                            "role_confidence": block.confidence,
                            **({"region_relevance_score": round(region_scores_by_block_id[block.block_id], 6)} if block.block_id in region_scores_by_block_id else {}),
                        },
                    )
                    builder.attach_span_to_section(span_id, section_id)
                    chronology_rank += 1
                continue

            current_section_id, current_path = section_stack[-1][1], section_stack[-1][2]
            span_id = builder.add_span(
                text=block.text,
                normalized_text=block.text,
                page_ref=PageRef(page_index=block.page_index),
                bbox=block.bbox,
                section_path=current_path,
                chronology_rank=chronology_rank,
                authority_score=min(0.78, max(0.2, block.confidence)),
                source_layer=source_layer,
                metadata={
                    "kind": f"ocr_{block.role}",
                    **dict(block.metadata),
                    "source": block.source,
                    "winner_hypothesis_id": winner_hypothesis_id,
                    "winner_source": winner_source,
                    "role_confidence": block.confidence,
                    **({"region_relevance_score": round(region_scores_by_block_id[block.block_id], 6)} if block.block_id in region_scores_by_block_id else {}),
                },
            )
            builder.attach_span_to_section(span_id, current_section_id)
            if block.confidence < self._config.low_confidence_threshold:
                add_flag(
                    builder,
                    severity=ReviewSeverity.WARNING,
                    category=ReviewCategory.QUALITY,
                    message="OCR-derived span has low confidence and should be review-first.",
                    span_id=span_id,
                    metadata={"confidence": block.confidence, "source": block.source, "adapter": "pdf_ocr"},
                )
            if block.role == "table":
                add_flag(
                    builder,
                    severity=ReviewSeverity.INFO,
                    category=ReviewCategory.QUALITY,
                    message="OCR table-like region flattened into narrative span pending dedicated table OCR parser.",
                    span_id=span_id,
                    metadata={"adapter": "pdf_ocr", "code": "table_flattened_from_ocr"},
                )
            chronology_rank += 1
        return builder.build()

    @staticmethod
    def _unique_component(title: str, parent_path: tuple[str, ...], counts: dict[tuple[str, ...], int]) -> str:
        clean = " ".join(title.split())[:120] or "OCR Section"
        candidate_path = parent_path + (clean,)
        current = counts.get(candidate_path, 0)
        counts[candidate_path] = current + 1
        return clean if current == 0 else f"{clean} #{current + 1}"


def parse_pdf_ocr(*, router_input: RouterInput, parse_plan: ParsePlan, compiled_pack: Any):
    return PdfOcrAdapter().parse(router_input=router_input, parse_plan=parse_plan, compiled_pack=compiled_pack)
