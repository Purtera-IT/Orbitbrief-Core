"""Skipped-image culprit cards: skip + scope text / veto → PM ask."""
from orbitbrief_core.pm_handoff.question_generators import (
    candidates_from_skipped_image_culprits,
)


def _marker(*, page=7, kind="decorative", via="vlm_gate", ocr="", veto=None, caption=""):
    gv = {"kind": kind, "via": via}
    if ocr:
        gv["ocr_preview"] = ocr
    if veto is not None:
        gv["veto"] = {"meaningful_prob": veto, "model": "pdf_image_veto"}
    return {
        "id": f"atm_img_{page}",
        "atom_type": "image",
        "value": {
            "kind": "image_marker",
            "region_ref": f"page{page}/image1",
            "expected_content": caption,
            "gate_verdict": gv,
        },
        "source_refs": [{"filename": "install.pdf"}],
    }


def test_quantity_ocr_on_skip_makes_culprit_card():
    atoms = [_marker(ocr="18 Total Data Outlets Comm Cabinet")]
    out = candidates_from_skipped_image_culprits(atoms, project_mode="install")
    assert len(out) == 1
    ask = out[0].suggested_open_question.lower()
    assert "page 7" in ask
    assert "decorative" in ask or "skip" in ask
    assert "outlet" in ask or "18" in ask


def test_veto_alone_makes_culprit_card():
    atoms = [_marker(kind="logo", veto=0.93, caption="Figure B-2")]
    out = candidates_from_skipped_image_culprits(atoms, project_mode="install")
    assert len(out) == 1
    assert out[0].severity == "critical"
    assert "veto" in out[0].suggested_open_question.lower() or "meaningful" in out[0].suggested_open_question.lower()


def test_cpu_gate_skip_without_veto_ignored():
    atoms = [_marker(via="cpu_gate", ocr="18 Total Data Outlets")]
    assert candidates_from_skipped_image_culprits(atoms, project_mode="install") == []


def test_clean_logo_skip_without_signals_ignored():
    atoms = [_marker(kind="logo", ocr="Acme Corp")]
    assert candidates_from_skipped_image_culprits(atoms, project_mode="install") == []
