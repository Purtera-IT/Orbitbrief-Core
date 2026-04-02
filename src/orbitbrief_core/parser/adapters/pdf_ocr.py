from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from orbitbrief_core.parser.adapters.base import AbstractAdapter, AdapterInfo
from orbitbrief_core.parser.adapters.common import add_flag, extract_bytes, extract_path, make_builder
from orbitbrief_core.parser.adapters.pdf_common import arbitrate_hypotheses, ocr_hypotheses
from orbitbrief_core.parser.router import ParsePlan, RouterInput
from orbitbrief_core.parser.shared.types import PageRef, ReviewCategory, ReviewSeverity, SourceLayer


@dataclass(frozen=True, slots=True)
class PdfOcrParseConfig:
    attach_heading_spans: bool = True
    low_confidence_threshold: float = 0.58


class PdfOcrAdapter(AbstractAdapter):
    info = AdapterInfo(
        name="PdfOcrAdapter",
        modality="pdf_ocr",
        description="OCR-sensitive PDF adapter with optional OCR/layout backends and arbitration.",
        optional_dependencies=("fitz", "pytesseract", "paddleocr"),
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

        root_section_id = builder.add_section(title="PDF_OCR", section_path=("PDF_OCR",), metadata={"synthetic": True, "adapter": "pdf_ocr"})
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
                    metadata={"adapter": "pdf_ocr", "role": "heading", "source": block.source, **dict(block.metadata)},
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
                        metadata={"kind": "ocr_heading", "source": block.source, **dict(block.metadata)},
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
                metadata={"kind": f"ocr_{block.role}", "source": block.source, **dict(block.metadata)},
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
                    metadata={"adapter": "pdf_ocr"},
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
