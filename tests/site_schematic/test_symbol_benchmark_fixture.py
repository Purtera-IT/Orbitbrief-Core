from __future__ import annotations

import json
from pathlib import Path

from orbitbrief_core.parser.router import RouterInput
from orbitbrief_core.parser.site_schematic import build_site_schematic_bundle_from_router_input
from orbitbrief_core.parser.site_schematic.symbols.benchmark import (
    create_symbol_benchmark_seed,
    load_symbol_benchmark_seed,
    run_symbol_benchmark,
    validate_symbol_benchmark_seed,
)


SAMPLE_TEXT = """
<PARSED TEXT FOR PAGE: 1 / 2>
TC001 TELECOMM SYMBOL LIST
AP WIRELESS ACCESS POINT OUTLET
<PARSED TEXT FOR PAGE: 2 / 2>
TC100 FLOOR PLAN
AP
""".strip()


def test_symbol_benchmark_seed_round_trip_and_runtime_report(tmp_path: Path) -> None:
    bundle = build_site_schematic_bundle_from_router_input(
        RouterInput(
            doc_id="symbol-benchmark",
            filename="symbol-benchmark.pdf",
            mime_type="application/pdf",
            metadata={"full_text": SAMPLE_TEXT},
        )
    )
    benchmark = create_symbol_benchmark_seed(bundle=bundle, packet_id="packet-symbol-benchmark")
    errors = validate_symbol_benchmark_seed(benchmark)
    assert not errors
    path = tmp_path / "benchmark.json"
    path.write_text(json.dumps(benchmark, ensure_ascii=True), encoding="utf-8")
    loaded = load_symbol_benchmark_seed(path)
    report = run_symbol_benchmark(bundle=bundle, benchmark=loaded)
    assert report["expectation_count"] >= 1
    assert "candidate_match_rate" in report
    assert "detector_class_coverage_rate" in report
    assert "detector_class_sparse_under_3" in report
    assert "per_family_false_positive_proxy" in report


def test_judgment_pdf_symbol_benchmark_fixtures_validate() -> None:
    fixture_dir = Path(__file__).parent / "fixtures"
    for name in ("symbol_benchmark_wireless.json", "symbol_benchmark_low_voltage.json"):
        benchmark = load_symbol_benchmark_seed(fixture_dir / name)
        errors = validate_symbol_benchmark_seed(benchmark)
        assert not errors
        assert benchmark.get("vocabulary_version")
        assert benchmark.get("detector_map_version")
        assert benchmark.get("detector_class_ids")
        assert benchmark.get("focus_class_ids")
        assert benchmark.get("expectations")
        first = benchmark["expectations"][0]
        assert "tier1_family" in first
        assert "tier2_family" in first
        assert "training_plan" in first
        assert "detector_class_id" in first
        assert "detector_selected_for_first_pass" in first
