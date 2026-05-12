from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from orbitbrief_core.parser.adapters.base import AbstractAdapter, AdapterInfo
from orbitbrief_core.parser.adapters.common import add_flag, extract_bytes, extract_path, make_builder
from orbitbrief_core.parser.adapters.pdf_common import arbitrate_hypotheses, text_hypotheses
from orbitbrief_core.parser.adapters.pdf_page_judge import HardPageJudge, run_hard_page_judge
from orbitbrief_core.parser.adapters.providers.vl_embedding_provider import VLEmbeddingProvider, candidate_from_block
from orbitbrief_core.parser.graph.scorers.region_relevance import RegionRelevanceRequest, RegionRelevanceScoringService
from orbitbrief_core.parser.router import ParsePlan, RouterInput
from orbitbrief_core.parser.shared.types import PageRef, ReviewCategory, ReviewSeverity


@dataclass(frozen=True, slots=True)
class PdfTextParseConfig:
    attach_heading_spans: bool = True
    flatten_tables: bool = True
    multimodal_region_relevance: bool = True
    hard_page_judge: bool = True


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
                    message="Hard-page judge evaluated disputed PDF page hypotheses.",
                    metadata={
                        "adapter": "pdf_text",
                        "abstained": judge_decision.abstained,
                        "reason_codes": list(judge_decision.reason_codes),
                    },
                )
        winner_hypothesis_id = str(arbitration.metadata.get("winner_hypothesis_id", "unknown"))
        winner_source = str(arbitration.metadata.get("winner", "unknown"))
        arbitration_reason_codes = tuple(str(code) for code in arbitration.metadata.get("arbitration_reason_codes", ()))

        root_section_id = builder.add_section(
            title="PDF",
            section_path=("PDF",),
            metadata={
                "synthetic": True,
                "adapter": "pdf_text",
                "winner_hypothesis_id": winner_hypothesis_id,
                "winner_source": winner_source,
            },
        )
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

        region_scores_by_block_id: dict[str, float] = {}
        if self._config.multimodal_region_relevance and {"table_attachment_dispute", "section_boundary_dispute"} & set(arbitration_reason_codes):
            provider = VLEmbeddingProvider(available=False)
            region_scorer = RegionRelevanceScoringService(backend=provider.score_region_relevance, threshold=0.72, max_fanout=3)
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
                    for block in page_blocks[:12]
                )
                query = " ".join(block.text for block in page_blocks[:3]).strip()
                if not query or not candidates:
                    continue
                relevance = region_scorer.score(
                    RegionRelevanceRequest(
                        page_index=page_index,
                        query_text=query,
                        candidate_regions=candidates,
                        packet_family_hint=None,
                        anchor_span_id=None,
                    )
                )
                for item in relevance:
                    if item.abstained or item.score is None:
                        continue
                    region_scores_by_block_id[item.region_id] = max(region_scores_by_block_id.get(item.region_id, 0.0), float(item.score))
            if region_scores_by_block_id:
                add_flag(
                    builder,
                    severity=ReviewSeverity.INFO,
                    category=ReviewCategory.AMBIGUITY,
                    message="Multimodal region relevance applied to bounded disputed PDF regions.",
                    metadata={"adapter": "pdf_text", "scored_regions": len(region_scores_by_block_id)},
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
                    metadata={
                        "adapter": "pdf_text",
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
                        authority_score=min(1.0, max(0.65, block.confidence)),
                        metadata={
                            "kind": "pdf_heading",
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
                metadata={
                    "kind": f"pdf_{block.role}",
                    **dict(block.metadata),
                    "source": block.source,
                    "winner_hypothesis_id": winner_hypothesis_id,
                    "winner_source": winner_source,
                    "role_confidence": block.confidence,
                    **({"region_relevance_score": round(region_scores_by_block_id[block.block_id], 6)} if block.block_id in region_scores_by_block_id else {}),
                },
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
