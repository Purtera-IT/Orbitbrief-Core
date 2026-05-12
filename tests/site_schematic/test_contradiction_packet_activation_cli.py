from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from orbitbrief_core.parser.site_schematic.contradiction_eval import (
    load_contradiction_packet_registry,
    validate_contradiction_packet_registry,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _fixture(name: str) -> Path:
    return Path(__file__).resolve().parent / "fixtures" / name


def test_registry_accepts_extended_onboarding_statuses() -> None:
    registry = load_contradiction_packet_registry(_fixture("contradiction_packet_registry.json"))
    packets = list(registry.get("packets", []))
    packets.append(
        {
            "packet_id": "synthetic_status_packet",
            "packet_label": "Synthetic Status Packet",
            "pdf_path": "pdfs/synthetic_status_packet.pdf",
            "contradiction_manifest_path": "contradiction_manifest_wireless_real.json",
            "packet_type": "detail_installation_conflict",
            "onboarding_status": "missing_pdf",
        }
    )
    registry["packets"] = packets
    errors = validate_contradiction_packet_registry(registry)
    assert errors == []


def test_activate_command_emits_packet_reports_for_selected_packet(tmp_path: Path) -> None:
    combined = tmp_path / "activation_combined.json"
    output_dir = tmp_path / "packet_reports"
    command = [
        sys.executable,
        "tools/run_contradiction_packet_eval.py",
        "activate",
        "--registry",
        "tests/site_schematic/fixtures/contradiction_packet_registry.json",
        "--packet-id",
        "rack_equipment_role_conflict_packet_01",
        "--output-dir",
        str(output_dir),
        "--output",
        str(combined),
    ]
    completed = subprocess.run(command, cwd=_repo_root(), check=True, capture_output=True, text=True)
    assert completed.returncode == 0
    assert combined.exists()
    packet_file = output_dir / "contradiction_packet_activation_rack_equipment_role_conflict_packet_01.json"
    assert packet_file.exists()
    payload = json.loads(combined.read_text(encoding="utf-8"))
    assert payload["kpi_view"] == "contradiction_packet_activation"
    assert payload["selected_packet_ids"] == ["rack_equipment_role_conflict_packet_01"]
    activation_summary = payload["activation_summary"]
    assert "activation_status_counts" in activation_summary
    packet_payload = json.loads(packet_file.read_text(encoding="utf-8"))
    assert packet_payload["packet_id"] == "rack_equipment_role_conflict_packet_01"
    assert packet_payload["status"] in {"missing_pdf", "evaluated"}
    assert packet_payload["activation_status"] in {"missing_pdf", "evaluated", "needs_manifest_revision"}
