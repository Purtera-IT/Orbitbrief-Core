"""``python -m orbitbrief_core.orchestrator compile`` works as advertised."""
from __future__ import annotations

import json
from pathlib import Path

from orbitbrief_core.orchestrator.__main__ import main


def test_cli_substrate_only_run(
    msp_envelope_path: Path, tmp_path: Path, capsys
) -> None:
    """No --ollama flag → substrate-only run, exit 0, manifest printed."""
    out_dir = tmp_path / "artifacts"
    rc = main(["compile", str(msp_envelope_path), "--out", str(out_dir)])
    assert rc == 0
    captured = capsys.readouterr()
    manifest = json.loads(captured.out)
    assert manifest["envelope_path"] == str(msp_envelope_path)
    assert manifest["skipped_brains_no_chat"] is True
    assert manifest["stage_status_counts"].get("ok", 0) >= 3


def test_cli_missing_envelope_returns_nonzero(tmp_path: Path, capsys) -> None:
    rc = main(["compile", str(tmp_path / "nope.json"), "--out", str(tmp_path / "out")])
    assert rc == 1
    err = capsys.readouterr().err
    assert "envelope not found" in err
