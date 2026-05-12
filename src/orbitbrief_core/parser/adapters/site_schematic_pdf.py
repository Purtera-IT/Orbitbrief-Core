from __future__ import annotations

from dataclasses import replace
from typing import Any

from orbitbrief_core.parser.adapters.base import AdapterInfo
from orbitbrief_core.parser.adapters.cad_pdf import CadPdfAdapter
from orbitbrief_core.parser.router import ParsePlan, RouterInput
from orbitbrief_core.parser.site_schematic import build_site_schematic_bundle_from_router_input


class SiteSchematicPdfAdapter(CadPdfAdapter):
    info = AdapterInfo(
        name="SiteSchematicPdfAdapter",
        modality="site_schematic_pdf",
        description="Site-schematic PDF adapter built on the stable drawing-packet CAD lane.",
    )

    def parse(self, *, router_input: RouterInput, parse_plan: ParsePlan, compiled_pack: Any):
        result = super().parse(router_input=router_input, parse_plan=parse_plan, compiled_pack=compiled_pack)
        bundle = build_site_schematic_bundle_from_router_input(router_input, source_modality="site_schematic_pdf")
        metadata = dict(result.metadata)
        metadata["site_schematic_bundle"] = bundle.to_dict()
        metadata["site_schematic_summary"] = bundle.summary()
        metadata["site_schematic_alias"] = "site_schematic_pdf"
        return replace(result, metadata=metadata)


def parse_site_schematic_pdf(*, router_input: RouterInput, parse_plan: ParsePlan, compiled_pack: Any):
    return SiteSchematicPdfAdapter().parse(router_input=router_input, parse_plan=parse_plan, compiled_pack=compiled_pack)
