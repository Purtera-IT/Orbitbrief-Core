from __future__ import annotations

from orbitbrief_core.runtime_spine.extractors.packet_to_claims import PacketExtractionContext, extract_claims_from_packet


def _packet(*, family: str, rows: list[dict], primary_span_id: str) -> dict:
    return {
        "packet_id": f"packet:test:{family}",
        "span_ids": tuple(str(row.get("span_id")) for row in rows),
        "primary_span_id": primary_span_id,
        "confidence": 0.84,
        "evidence_rows": rows,
        "metadata": {
            "packet_family": family,
            "packet_state": "extract",
            "uncertainty_markers": (),
        },
    }


def test_network_room_packet_prefers_room_rows_over_sheet_metadata() -> None:
    rows = [
        {
            "span_id": "s1",
            "text": "Sheet Title: Telecom Floor Plan",
            "metadata": {"kind": "title_block_field", "page_index": 0},
        },
        {
            "span_id": "s2",
            "text": "MDF-01 Telecom Room",
            "metadata": {"kind": "room_label", "page_index": 0, "region_scope": "floorplan"},
        },
    ]
    packet = _packet(family="network_room_or_closet_packet", rows=rows, primary_span_id="s1")
    claims, _ = extract_claims_from_packet(packet, PacketExtractionContext(role_id="transcript_or_notes", modality="cad_sheet"))
    assert len(claims) == 1
    assert "MDF-01" in claims[0].claim_body
    assert "Sheet Title" not in claims[0].claim_body


def test_equipment_packet_prefers_equipment_rows_over_legend_rows() -> None:
    rows = [
        {
            "span_id": "s1",
            "text": "LEGEND: AP = Access Point, WAP = Wireless AP",
            "metadata": {"kind": "legend", "page_index": 0},
        },
        {
            "span_id": "s2",
            "text": "AP-12 terminate at nearest IDF",
            "metadata": {"kind": "equipment_label", "page_index": 0, "near_symbol": True},
        },
    ]
    packet = _packet(family="equipment_reference_packet", rows=rows, primary_span_id="s1")
    claims, _ = extract_claims_from_packet(packet, PacketExtractionContext(role_id="transcript_or_notes", modality="cad_sheet"))
    assert len(claims) == 1
    assert "AP-12" in claims[0].claim_body
    assert "facts:" in claims[0].claim_body


def test_constructability_packet_extracts_distance_aff_and_routing_patterns() -> None:
    rows = [
        {
            "span_id": "s1",
            "text": "NOT TO SCALE / DETAILS",
            "metadata": {"kind": "title_block_field", "page_index": 0},
        },
        {
            "span_id": "s2",
            "text": "Install AP at 10' AFF, keep 20' slack, homerun to nearest IDF.",
            "metadata": {"kind": "note_block", "page_index": 0},
        },
    ]
    packet = _packet(family="constructability_packet", rows=rows, primary_span_id="s1")
    claims, _ = extract_claims_from_packet(packet, PacketExtractionContext(role_id="transcript_or_notes", modality="cad_sheet"))
    assert len(claims) == 1
    body = claims[0].claim_body
    assert "10' AFF" in body
    assert "homerun to" in body.lower()
    assert "facts:" in body
