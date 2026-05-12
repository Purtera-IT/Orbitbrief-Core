from __future__ import annotations

from pathlib import Path
from typing import Any

from orbitbrief_core.parser.router import RouterInput
from orbitbrief_core.parser.site_schematic.contradiction_eval import run_contradiction_benchmark
from orbitbrief_core.parser.site_schematic.core import build_site_schematic_bundle_from_router_input
from orbitbrief_core.parser.site_schematic.models import SiteSchematicBundle
from orbitbrief_core.parser.site_schematic.symbols.benchmark import run_symbol_benchmark, run_topology_benchmark


def build_calibrated_bundle_for_eval(
    *,
    pdf_path: Path,
    packet_id: str,
    predictions_path: Path | None = None,
) -> SiteSchematicBundle:
    metadata: dict[str, Any] = {"path": str(pdf_path)}
    if predictions_path is not None:
        metadata["symbol_detector_predictions_path"] = str(predictions_path)
    return build_site_schematic_bundle_from_router_input(
        RouterInput(
            doc_id=pdf_path.stem or packet_id,
            filename=pdf_path.name,
            mime_type="application/pdf",
            metadata=metadata,
        )
    )


def build_aligned_symbol_topology_kpi_view(
    *,
    bundle: SiteSchematicBundle,
    benchmark: dict[str, Any],
    run_mode: str = "canonical_calibrated",
) -> dict[str, Any]:
    symbol_report = run_symbol_benchmark(bundle=bundle, benchmark=benchmark)
    topology_report = run_topology_benchmark(bundle=bundle)
    return {
        "run_mode": run_mode,
        "topology_additive_only": True,
        "symbol_kpi": symbol_report,
        "topology_kpi": topology_report,
        "diagnostics": {
            "symbol_kpi_view": symbol_report.get("kpi_view", "canonical_symbol"),
            "topology_kpi_view": topology_report.get("kpi_view", "additive_topology"),
            "topology_perturbs_symbol_scores": False,
        },
    }


def build_contradiction_eval_view(
    *,
    bundle: SiteSchematicBundle,
    contradiction_benchmark: dict[str, Any],
    run_mode: str = "contradiction_benchmark",
) -> dict[str, Any]:
    contradiction_report = run_contradiction_benchmark(
        bundle=bundle,
        benchmark=contradiction_benchmark,
    )
    return {
        "run_mode": run_mode,
        "truth_path_unchanged": True,
        "contradiction_eval": contradiction_report,
        "diagnostics": {
            "kpi_view": contradiction_report.get("kpi_view", "contradiction_benchmark"),
            "advisory_only": True,
        },
    }


def build_aligned_symbol_topology_and_contradiction_view(
    *,
    bundle: SiteSchematicBundle,
    benchmark: dict[str, Any],
    contradiction_benchmark: dict[str, Any],
    run_mode: str = "canonical_plus_contradiction_eval",
) -> dict[str, Any]:
    kpi_view = build_aligned_symbol_topology_kpi_view(
        bundle=bundle,
        benchmark=benchmark,
        run_mode="canonical_calibrated",
    )
    contradiction_view = build_contradiction_eval_view(
        bundle=bundle,
        contradiction_benchmark=contradiction_benchmark,
        run_mode="contradiction_benchmark",
    )
    return {
        "run_mode": run_mode,
        "symbol_kpi": kpi_view.get("symbol_kpi", {}),
        "topology_kpi": kpi_view.get("topology_kpi", {}),
        "contradiction_eval": contradiction_view.get("contradiction_eval", {}),
        "diagnostics": {
            "symbol_kpi_view": (kpi_view.get("symbol_kpi", {}) or {}).get("kpi_view", "canonical_symbol"),
            "topology_kpi_view": (kpi_view.get("topology_kpi", {}) or {}).get("kpi_view", "additive_topology"),
            "contradiction_kpi_view": (contradiction_view.get("contradiction_eval", {}) or {}).get(
                "kpi_view", "contradiction_benchmark"
            ),
            "truth_path_unchanged": True,
            "topology_additive_only": True,
        },
    }

