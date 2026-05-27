"""One-shot: inject a ``brain:`` block into every pack in domain_packs.yaml.

Surgical text edit (preserves comments, key order, multiline strings) by
locating each ``- id: <pack>`` block and inserting the brain block after
the matching ``display_name:`` line.

Run once: ``python tools/inject_brain_blocks.py``.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

YAML_PATH = Path(__file__).resolve().parent.parent / "src" / "orbitbrief_core" / "world_model" / "data" / "domain_packs.yaml"


# pack_id → (intent, implementation, extra_aliases)
# intent='implemented' means we run an LLM brain; 'none' means SOW-validator only.
# implementation is the brain folder name; aliases are extra surface forms beyond intake_aliases.
BRAIN_MAP: dict[str, tuple[str, str, list[str]]] = {
    # ── packs WITH a brain implementation ─────────────────────────
    "wireless": ("implemented", "wireless", []),
    "low_voltage_cabling": ("implemented", "low_voltage_cabling", ["copper_cabling", "structured_cabling"]),
    "rack_and_stack": ("implemented", "rack_and_stack", []),
    "datacenter": ("implemented", "datacenter", []),
    "imac": ("implemented", "imac", []),
    "msp": ("implemented", "managed_services", ["managed_services"]),
    "audio_visual": ("implemented", "audio_visual", ["av"]),
    "building_management_systems": ("implemented", "building_management_systems", ["bms"]),
    "network_maintenance": ("implemented", "network_maintenance", ["networking"]),
    "camera_vms_operations": ("implemented", "camera_vms_operations", []),
    "procurement_finance": ("implemented", "procurement_finance", []),
    "electrical": ("implemented", "electrical", []),
    "professional_services": ("implemented", "professional_services", []),
    "audit": ("implemented", "audit", []),

    # ── REDIRECTS — pack matches but runs a different brain ───────
    "security_camera": ("implemented", "camera_vms_operations", ["video_surveillance", "vms", "cctv", "surveillance"]),

    # ── packs WITHOUT a brain (validator-only / no LLM scope) ─────
    "alm": ("none", "alm", []),
    "commercial": ("none", "commercial", []),
    "data_migration": ("none", "data_migration", []),
    "delivery_execution": ("none", "delivery_execution", ["delivery_wave_management"]),
    "hardware": ("none", "hardware", []),
    "itad": ("none", "itad", []),
    "other": ("none", "other", []),
    "security_access": ("none", "security_access", ["access_control", "eacs"]),
    "site_structure": ("none", "site_structure", []),
    "staff_augmentation": ("none", "staff_augmentation", []),
    "telecom": ("none", "telecom", []),
    "paging_mass_notification": ("none", "paging_mass_notification", ["paging", "emergency_notification"]),
    "fire_safety": ("none", "fire_safety", []),
    "das": ("none", "das", ["distributed_antenna_system"]),
}


def render_brain_block(intent: str, implementation: str, aliases: list[str]) -> list[str]:
    """Render the YAML lines for a brain: block, two-space indented under the pack."""
    lines = ["  brain:"]
    lines.append(f"    intent: {intent}")
    lines.append(f"    implementation: {implementation}")
    if aliases:
        lines.append("    aliases:")
        for a in aliases:
            lines.append(f"    - {a}")
    else:
        lines.append("    aliases: []")
    return lines


def main() -> int:
    src = YAML_PATH.read_text(encoding="utf-8").splitlines()

    out: list[str] = []
    i = 0
    current_pack: str | None = None
    already_has_brain = False
    skipped_existing: list[str] = []
    injected: list[str] = []

    while i < len(src):
        line = src[i]
        # Detect start of a pack entry.
        m = re.match(r"^- id:\s*([A-Za-z0-9_]+)\s*$", line)
        if m:
            current_pack = m.group(1)
            already_has_brain = False
            # peek ahead for an existing brain: block within this pack
            j = i + 1
            while j < len(src) and not re.match(r"^- id:", src[j]):
                if re.match(r"^\s+brain:\s*$", src[j]):
                    already_has_brain = True
                    break
                j += 1
            out.append(line)
            i += 1
            continue

        # Inject after display_name line if this pack is in our map.
        if (
            current_pack is not None
            and not already_has_brain
            and re.match(r"^\s+display_name:", line)
            and current_pack in BRAIN_MAP
        ):
            out.append(line)
            intent, impl, aliases = BRAIN_MAP[current_pack]
            out.extend(render_brain_block(intent, impl, aliases))
            injected.append(current_pack)
            current_pack = None  # only inject once per pack
            i += 1
            continue

        if already_has_brain and current_pack and re.match(r"^- id:", line):
            skipped_existing.append(current_pack)

        out.append(line)
        i += 1

    YAML_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")

    unmapped = []
    for pack in BRAIN_MAP:
        if pack not in injected and pack not in skipped_existing:
            unmapped.append(pack)

    print(f"injected brain: block into {len(injected)} packs")
    for p in injected:
        intent, impl, _ = BRAIN_MAP[p]
        tag = "→" + impl if impl != p else ""
        print(f"  + {p:30s} intent={intent:11s} {tag}")
    if skipped_existing:
        print(f"skipped (already had brain block): {skipped_existing}")
    if unmapped:
        print(f"WARNING — in BRAIN_MAP but pack id not found in YAML: {unmapped}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
