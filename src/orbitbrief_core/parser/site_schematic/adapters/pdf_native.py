from __future__ import annotations

from orbitbrief_core.parser.router import RouterInput
from orbitbrief_core.parser.site_schematic.core import extract_page_texts


def extract_pdf_page_texts(router_input: RouterInput) -> list[str]:
    return extract_page_texts(router_input)
