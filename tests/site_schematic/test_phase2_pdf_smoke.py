from __future__ import annotations

from pathlib import Path

import pytest

from orbitbrief_core.parser.router import RouterInput
from orbitbrief_core.parser.site_schematic import build_site_schematic_bundle_from_router_input

from .gold_eval import resolve_fixture_pdf


WIRELESS_PDF = resolve_fixture_pdf('wireless')
SOUTHERN_POST_PDF = resolve_fixture_pdf('low_voltage')


def _bundle(path: Path):
    return build_site_schematic_bundle_from_router_input(
        RouterInput(doc_id=path.stem, filename=path.name, mime_type='application/pdf', metadata={'path': str(path)}),
        source_modality='site_schematic_pdf',
    )


@pytest.mark.skipif(not WIRELESS_PDF.exists(), reason='wireless smoke PDF not available in this environment')
def test_wireless_pdf_smoke_phase2_symbol_linking() -> None:
    bundle = _bundle(WIRELESS_PDF)
    assert bundle.pages[0].sheet_type == 'legend_symbol'
    assert bundle.pages[-1].sheet_type == 'installation_detail'
    assert bundle.summary()['typed_pages'] == bundle.summary()['page_count']
    assert bundle.summary()['symbol_instances'] > 0
    ap_links = [link for link in bundle.symbol_links if link.symbol_token == 'AP']
    assert ap_links
    assert any(link.status == 'linked' for link in ap_links)
    assert any('wireless' in entry.description.lower() or 'wap' in entry.description.lower() for entry in bundle.legend_entries)
    assert any('wm' == entry.token.lower() for entry in bundle.abbreviations)
    assert 'page_parser' in bundle.model_registry


@pytest.mark.skipif(not SOUTHERN_POST_PDF.exists(), reason='Southern Post smoke PDF not available in this environment')
def test_southern_post_pdf_smoke_phase2_sheet_typing_and_notes() -> None:
    bundle = _bundle(SOUTHERN_POST_PDF)
    assert bundle.pages[0].sheet_type == 'notes_spec'
    assert bundle.pages[1].sheet_type == 'legend_symbol'
    assert bundle.pages[2].sheet_type == 'schedule_sheet'
    assert any(page.sheet_type == 'equipment_room_layout' for page in bundle.pages)
    notes = [obs.text for obs in bundle.observations if obs.kind == 'note_clause']
    assert any('70°f' in note.lower() or '70f' in note.lower() for note in notes)
    assert any('#6 awg' in note.lower() or '6 awg' in note.lower() for note in notes)
    assert any('pull box' in note.lower() for note in notes)
    drawing_rows = [obs.text for obs in bundle.observations if obs.kind == 'drawing_index_row']
    assert any('T906' in row for row in drawing_rows)
