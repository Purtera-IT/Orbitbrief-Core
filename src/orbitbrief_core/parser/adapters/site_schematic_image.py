from __future__ import annotations

from dataclasses import replace
from typing import Any

from orbitbrief_core.parser.adapters.base import AdapterInfo
from orbitbrief_core.parser.adapters.cad_image import CadImageAdapter
from orbitbrief_core.parser.router import ParsePlan, RouterInput
from orbitbrief_core.parser.site_schematic import build_site_schematic_bundle_from_router_input


class SiteSchematicImageAdapter(CadImageAdapter):
    info = AdapterInfo(
        name="SiteSchematicImageAdapter",
        modality="site_schematic_image",
        description="Site-schematic image adapter built on the stable drawing-packet image lane.",
    )

    def parse(self, *, router_input: RouterInput, parse_plan: ParsePlan, compiled_pack: Any):
        result = super().parse(router_input=router_input, parse_plan=parse_plan, compiled_pack=compiled_pack)
        bundle = build_site_schematic_bundle_from_router_input(router_input, source_modality="site_schematic_image")
        metadata = dict(result.metadata)
        metadata["site_schematic_bundle"] = bundle.to_dict()
        metadata["site_schematic_summary"] = bundle.summary()
        metadata["site_schematic_alias"] = "site_schematic_image"
        return replace(result, metadata=metadata)


def parse_site_schematic_image(*, router_input: RouterInput, parse_plan: ParsePlan, compiled_pack: Any):
    return SiteSchematicImageAdapter().parse(router_input=router_input, parse_plan=parse_plan, compiled_pack=compiled_pack)
