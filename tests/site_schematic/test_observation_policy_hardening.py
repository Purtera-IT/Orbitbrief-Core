from __future__ import annotations

from pathlib import Path

import fitz

from orbitbrief_core.parser.adapters.providers.base import ProviderLayoutBlock, ProviderPdfHypothesis
from orbitbrief_core.parser.router import RouterInput
from orbitbrief_core.parser.site_schematic.models import SiteSchematicSubregion
from orbitbrief_core.parser.site_schematic.observations import build_site_schematic_page_observations
from orbitbrief_core.parser.site_schematic.zoning.page_zones import build_pseudo_pages


def _make_dense_pdf(path: Path, *, rows: int = 120) -> None:
    doc = fitz.open()
    page = doc.new_page(width=1000, height=1400)
    page.insert_text((72, 40), "T001 SYMBOLS & LEGENDS", fontsize=14)
    y = 80
    for idx in range(rows):
        page.insert_text((72, y), f"T{idx:03d} | LEGEND ITEM {idx}", fontsize=9)
        y += 10
    doc.save(path)
    doc.close()


def test_policy_uses_native_only_for_conservative_floorplans(tmp_path: Path) -> None:
    pdf_path = tmp_path / "floorplan.pdf"
    _make_dense_pdf(pdf_path, rows=30)
    observations, diagnostics = build_site_schematic_page_observations(
        router_input=RouterInput(
            doc_id="policy-floorplan",
            filename=pdf_path.name,
            mime_type="application/pdf",
            metadata={"path": str(pdf_path)},
        ),
        page_texts=[""],
        model_registry={
            "observation_layer": {"enabled": True, "docling_merge_enabled": True},
            "pdf_backbone": {"enabled": True},
        },
        sheet_types=["floorplan_overall"],
    )
    assert observations
    assert diagnostics["pages"][0]["provider_path"] == "native_only"
    assert diagnostics["provider_status"]["docling"]["selected_page_count"] == 0


def test_policy_applies_block_budget_for_aggressive_sheets(monkeypatch, tmp_path: Path) -> None:
    pdf_path = tmp_path / "legend.pdf"
    _make_dense_pdf(pdf_path, rows=60)

    def _fake_docling(*_args, **_kwargs):
        blocks = tuple(
            ProviderLayoutBlock(
                block_id=f"d:{idx}",
                page_index=0,
                bbox=(10.0, float(idx), 500.0, float(idx + 5)),
                text=f"LEGEND EXTRA {idx}",
                role="paragraph",
                confidence=0.95,
                source="docling",
                metadata={},
            )
            for idx in range(150)
        )
        return ProviderPdfHypothesis(
            hypothesis_id="hypothesis:docling",
            source="docling",
            page_blocks=blocks,
            table_regions=(),
            confidence=0.9,
            metadata={"degraded": False},
        )

    monkeypatch.setattr("orbitbrief_core.parser.site_schematic.observations.extract_docling_pdf_hypothesis", _fake_docling)

    observations, diagnostics = build_site_schematic_page_observations(
        router_input=RouterInput(
            doc_id="policy-legend",
            filename=pdf_path.name,
            mime_type="application/pdf",
            metadata={"path": str(pdf_path)},
        ),
        page_texts=[""],
        model_registry={
            "observation_layer": {
                "enabled": True,
                "docling_merge_enabled": True,
                "docling_limited_block_budget": 30,
                "docling_full_block_budget": 40,
            },
            "pdf_backbone": {"enabled": True},
        },
        sheet_types=["legend_symbol"],
    )
    assert observations
    page_diag = diagnostics["pages"][0]
    assert page_diag["provider_path"] in {"native_docling_limited", "native_docling_full"}
    assert page_diag["block_budget_applied"] is True
    assert page_diag["merged_block_count"] <= page_diag["block_budget"]


def test_mixed_detail_pseudo_pages_clustered() -> None:
    subregions = tuple(
        SiteSchematicSubregion(
            subregion_id=f"s:{idx}",
            page_index=12,
            parent_region_id="p12:detail_block",
            detail_region_id=f"d:{idx}",
            role="equipment_elevation" if idx % 2 == 0 else "detail_note_block",
            text=f"DETAIL {idx}",
            confidence=0.8,
            bbox=(0.1, 0.02 * idx, 0.9, 0.02 * idx + 0.015),
            source_mode="pdf_native_docling",
            metadata={},
        )
        for idx in range(1, 30)
    )
    pseudo = build_pseudo_pages(
        page_index=12,
        sheet_type="equipment_room_layout",
        text="",
        regions=(),
        subregions=subregions,
        page_observation=None,
    )
    assert len(pseudo) <= 8
    assert any(bool(row.metadata.get("clustering_applied")) for row in pseudo)


def test_lightweight_layout_tier_runs_selectively_on_hard_mixed_detail(monkeypatch, tmp_path: Path) -> None:
    pdf_path = tmp_path / "t900_like.pdf"
    _make_dense_pdf(pdf_path, rows=95)

    def _fake_docling(*_args, **_kwargs):
        blocks = tuple(
            ProviderLayoutBlock(
                block_id=f"d:{idx}",
                page_index=0,
                bbox=(40.0, float(20 + idx * 8), 560.0, float(26 + idx * 8)),
                text=f"DETAIL {idx} EQUIPMENT ELEVATION NOTE",
                role="paragraph",
                confidence=0.88,
                source="docling",
                metadata={},
            )
            for idx in range(20)
        )
        return ProviderPdfHypothesis(
            hypothesis_id="hypothesis:docling",
            source="docling",
            page_blocks=blocks,
            table_regions=(),
            confidence=0.86,
            metadata={"degraded": False},
        )

    def _fake_pp(*_args, **_kwargs):
        blocks = tuple(
            ProviderLayoutBlock(
                block_id=f"pp:{idx}",
                page_index=0,
                bbox=(30.0, float(40 + idx * 22), 580.0, float(58 + idx * 22)),
                text=f"GENERAL NOTES COLUMN {idx}",
                role="paragraph",
                confidence=0.84,
                source="pp_structure",
                metadata={"pp_type": "text"},
            )
            for idx in range(8)
        )
        return ProviderPdfHypothesis(
            hypothesis_id="hypothesis:pp_structure",
            source="pp_structure",
            page_blocks=blocks,
            table_regions=(),
            confidence=0.82,
            metadata={"degraded": False},
        )

    monkeypatch.setattr("orbitbrief_core.parser.site_schematic.observations.extract_docling_pdf_hypothesis", _fake_docling)
    monkeypatch.setattr("orbitbrief_core.parser.site_schematic.observations.extract_pp_structure_image_hypothesis", _fake_pp)
    monkeypatch.setattr(
        "orbitbrief_core.parser.site_schematic.observations._page_complexity_metrics",
        lambda _page: {"block_count": 120.0, "table_count": 4.0, "word_count": 300.0, "table_density": 0.2, "ambiguity": 0.6},
    )

    observations, diagnostics = build_site_schematic_page_observations(
        router_input=RouterInput(
            doc_id="policy-lightweight",
            filename=pdf_path.name,
            mime_type="application/pdf",
            metadata={"path": str(pdf_path)},
        ),
        page_texts=[""],
        model_registry={
            "observation_layer": {
                "enabled": True,
                "docling_merge_enabled": True,
                "lightweight_layout_enabled": True,
                "force_docling_all_pages": True,
            },
            "pdf_backbone": {"enabled": True},
            "layout_lightweight": {"enabled": True},
        },
        sheet_types=["equipment_room_layout"],
    )
    assert observations
    page_diag = diagnostics["pages"][0]
    assert page_diag["provider_path"] in {"native_docling_limited", "native_docling_full"}
    assert page_diag["use_lightweight_layout"] is True
    assert page_diag["lightweight_layout_used"] is True
    assert page_diag["layout_blocks_added"] > 0
    assert page_diag["lightweight_priority_profile"] in {"mixed_detail_first", "balanced_auto"}
    assert "policy_signals" in page_diag
    assert page_diag["policy_signals"]["fragmentation_risk"] > 0.0


def test_dynamic_priority_auto_prefers_legend_for_dense_legend_pages(monkeypatch, tmp_path: Path) -> None:
    pdf_path = tmp_path / "legend-dense.pdf"
    _make_dense_pdf(pdf_path, rows=80)
    monkeypatch.setattr(
        "orbitbrief_core.parser.site_schematic.observations._page_complexity_metrics",
        lambda _page: {"block_count": 120.0, "table_count": 8.0, "word_count": 350.0, "table_density": 0.5, "ambiguity": 0.6},
    )
    observations, diagnostics = build_site_schematic_page_observations(
        router_input=RouterInput(
            doc_id="policy-legend-auto",
            filename=pdf_path.name,
            mime_type="application/pdf",
            metadata={"path": str(pdf_path)},
        ),
        page_texts=[""],
        model_registry={
            "observation_layer": {
                "enabled": True,
                "docling_merge_enabled": True,
                "lightweight_layout_enabled": True,
                "lightweight_layout_priority_mode": "auto",
            },
            "pdf_backbone": {"enabled": True},
            "layout_lightweight": {"enabled": True},
        },
        sheet_types=["legend_symbol"],
    )
    assert observations
    page_diag = diagnostics["pages"][0]
    assert page_diag["lightweight_priority_profile"] == "legend_first"
    assert any("dynamic_priority:legend_dense" == code for code in page_diag["reason_codes"])


def test_debug_priority_override_is_honored(monkeypatch, tmp_path: Path) -> None:
    pdf_path = tmp_path / "mixed-detail-override.pdf"
    _make_dense_pdf(pdf_path, rows=80)
    monkeypatch.setattr(
        "orbitbrief_core.parser.site_schematic.observations._page_complexity_metrics",
        lambda _page: {"block_count": 118.0, "table_count": 3.0, "word_count": 310.0, "table_density": 0.2, "ambiguity": 0.6},
    )
    observations, diagnostics = build_site_schematic_page_observations(
        router_input=RouterInput(
            doc_id="policy-override",
            filename=pdf_path.name,
            mime_type="application/pdf",
            metadata={"path": str(pdf_path)},
        ),
        page_texts=[""],
        model_registry={
            "observation_layer": {
                "enabled": True,
                "docling_merge_enabled": True,
                "lightweight_layout_enabled": True,
                "lightweight_layout_priority_mode": "auto",
                "debug_priority_mode_override": "mixed_detail_first",
            },
            "pdf_backbone": {"enabled": True},
            "layout_lightweight": {"enabled": True},
        },
        sheet_types=["equipment_room_layout"],
    )
    assert observations
    page_diag = diagnostics["pages"][0]
    assert page_diag["lightweight_priority_profile"] == "mixed_detail_first"
    assert any("priority_override:mixed_detail_first" == code for code in page_diag["reason_codes"])
