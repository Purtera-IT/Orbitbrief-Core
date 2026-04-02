from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from orbitbrief_core.parser.adapters.base import AbstractAdapter, AdapterInfo
from orbitbrief_core.parser.adapters.common import add_flag, extract_bytes, extract_path, make_builder
from orbitbrief_core.parser.adapters.pdf_common import arbitrate_hypotheses, text_hypotheses
from orbitbrief_core.parser.router import ParsePlan, RouterInput
from orbitbrief_core.parser.shared.types import PageRef, ReviewCategory, ReviewSeverity


@dataclass(frozen=True, slots=True)
class PdfTextParseConfig:
    attach_heading_spans: bool = True
    flatten_tables: bool = True


class PdfTextAdapter(AbstractAdapter):
    info = AdapterInfo(
        name="PdfTextAdapter",
        modality="pdf_text",
        description="Born-digital PDF adapter with multi-hypothesis layout extraction and arbitration.",
        optional_dependencies=("fitz", "pdfplumber", "pypdf", "docling"),
    )

    def __init__(self, config: PdfTextParseConfig | None = None) -> None:
        self._config = config or PdfTextParseConfig()

    def parse(self, *, router_input: RouterInput, parse_plan: ParsePlan, compiled_pack: Any):
        builder = make_builder(router_input=router_input, parse_plan=parse_plan, compiled_pack=compiled_pack)
        pdf_path = extract_path(router_input)
        pdf_bytes = extract_bytes(router_input)
        hypotheses = text_hypotheses(pdf_path=pdf_path, pdf_bytes=pdf_bytes)
        arbitration = arbitrate_hypotheses(hypotheses)

        root_section_id = builder.add_section(title="PDF", section_path=("PDF",), metadata={"synthetic": True, "adapter": "pdf_text"})
        builder.set_section_root(root_section_id)

        if not hypotheses:
            add_flag(
                builder,
                severity=ReviewSeverity.WARNING,
                category=ReviewCategory.QUALITY,
                message="No PDF text parse hypotheses succeeded; parse result will be nearly empty.",
                metadata={"adapter": "pdf_text"},
            )
            return builder.build()

        for disagreement in arbitration.disagreements:
            add_flag(
                builder,
                severity=ReviewSeverity.INFO,
                category=ReviewCategory.AMBIGUITY,
                message=f"PDF arbitration disagreement: {disagreement}",
                metadata={"adapter": "pdf_text", "hypothesis_scores": dict(arbitration.hypothesis_scores)},
            )
        if arbitration.repeated_header_texts or arbitration.repeated_footer_texts:
            add_flag(
                builder,
                severity=ReviewSeverity.INFO,
                category=ReviewCategory.QUALITY,
                message="Repeated PDF headers/footers were detected and demoted during arbitration.",
                metadata={
                    "adapter": "pdf_text",
                    "headers": list(arbitration.repeated_header_texts),
                    "footers": list(arbitration.repeated_footer_texts),
                },
            )

        section_stack: list[tuple[int, str, tuple[str, ...]]] = [(0, root_section_id, ("PDF",))]
        section_name_counts: dict[tuple[str, ...], int] = {}
        chronology_rank = 0

        for block in arbitration.selected_blocks:
            if block.role == "noise":
                continue
            if block.role == "heading":
                title = self._unique_component(block.text, section_stack[-1][2], section_name_counts)
                parent_id, parent_path = section_stack[-1][1], section_stack[-1][2]
                section_path = parent_path + (title,)
                section_id = builder.add_section(
                    title=title,
                    section_path=section_path,
                    parent_section_id=parent_id,
                    metadata={"adapter": "pdf_text", "role": "heading", "source": block.source, **dict(block.metadata)},
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
                        authority_score=min(1.0, max(0.65, block.confidence)),
                        metadata={"kind": "pdf_heading", "source": block.source, **dict(block.metadata)},
                    )
                    builder.attach_span_to_section(span_id, section_id)
                    chronology_rank += 1
                continue

            current_section_id, current_path = section_stack[-1][1], section_stack[-1][2]
            if block.role == "table" and not self._config.flatten_tables:
                continue
            span_id = builder.add_span(
                text=block.text,
                normalized_text=block.text,
                page_ref=PageRef(page_index=block.page_index),
                bbox=block.bbox,
                section_path=current_path,
                chronology_rank=chronology_rank,
                authority_score=min(1.0, max(0.45, block.confidence)),
                metadata={"kind": f"pdf_{block.role}", "source": block.source, **dict(block.metadata)},
            )
            builder.attach_span_to_section(span_id, current_section_id)
            if block.role == "table":
                add_flag(
                    builder,
                    severity=ReviewSeverity.INFO,
                    category=ReviewCategory.QUALITY,
                    message="PDF table-like region flattened into narrative span pending dedicated table parser.",
                    span_id=span_id,
                    metadata={"adapter": "pdf_text"},
                )
            chronology_rank += 1

        for table in arbitration.selected_tables:
            add_flag(
                builder,
                severity=ReviewSeverity.INFO,
                category=ReviewCategory.QUALITY,
                message="Structured table region detected in PDF text lane.",
                metadata={"adapter": "pdf_text", "page_index": table.page_index, "source": table.source},
            )
        return builder.build()

    @staticmethod
    def _unique_component(title: str, parent_path: tuple[str, ...], counts: dict[tuple[str, ...], int]) -> str:
        clean = " ".join(title.split())[:120] or "Section"
        candidate_path = parent_path + (clean,)
        current = counts.get(candidate_path, 0)
        counts[candidate_path] = current + 1
        return clean if current == 0 else f"{clean} #{current + 1}"


def parse_pdf_text(*, router_input: RouterInput, parse_plan: ParsePlan, compiled_pack: Any):
    return PdfTextAdapter().parse(router_input=router_input, parse_plan=parse_plan, compiled_pack=compiled_pack)
