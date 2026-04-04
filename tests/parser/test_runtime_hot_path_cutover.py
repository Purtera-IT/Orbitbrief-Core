from __future__ import annotations

from dataclasses import dataclass

from orbitbrief_core.parser.router import RouterInput
from orbitbrief_core.parser.runtime import parse_extract_and_postprocess, run_parser_runtime
from orbitbrief_core.runtime_spine import pipeline as runtime_pipeline


@dataclass(frozen=True, slots=True)
class _ManifestStub:
    pack_id: str = "professional_services_text"
    role_id: str = "transcript_or_notes"


@dataclass(frozen=True, slots=True)
class _CompiledPackStub:
    manifest: _ManifestStub
    parser_profiles: dict


def _compiled_pack_stub() -> _CompiledPackStub:
    rows = [{"modality": "txt", "parser_profile_id": "parser:professional_services_text:txt"}]
    return _CompiledPackStub(manifest=_ManifestStub(), parser_profiles={"rows": rows})


def test_run_parser_runtime_returns_parse_bundle_only() -> None:
    compiled_pack = _compiled_pack_stub()
    text = "Scope includes parser runtime delivery.\nAssumption: customer provides access."
    router_input = RouterInput(
        doc_id="runtime_cutover_001",
        filename="notes.txt",
        raw_text_preview=text,
        metadata={"raw_text": text},
    )

    bundle = run_parser_runtime(router_input=router_input, compiled_pack=compiled_pack)

    assert bundle.packet_candidates
    assert isinstance(bundle.diagnostics, dict)
    events = bundle.diagnostics.get("events", ())
    assert any(event.startswith("phase:packetizer") for event in events)
    assert all(not str(event).startswith("phase:extractor") for event in events)


def test_legacy_parse_extract_facade_delegates_to_runtime_spine(monkeypatch) -> None:
    captured: dict[str, object] = {}
    sentinel = object()

    def _fake_hot_path(**kwargs):
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(runtime_pipeline, "parse_extract_and_postprocess", _fake_hot_path)
    result = parse_extract_and_postprocess(router_input=RouterInput(doc_id="x"), compiled_pack=object())

    assert result is sentinel
    assert "router_input" in captured
    assert "compiled_pack" in captured
