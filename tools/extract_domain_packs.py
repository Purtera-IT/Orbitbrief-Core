"""Regenerate ``world_model/data/domain_packs.yaml`` from the intake workbook.

Source of truth: ``AWESOME_CHASE_orbitbrief_domain_only_schema_intake_workbook_v4.xlsx``.

Run after the workbook is updated:

    python tools/extract_domain_packs.py path/to/workbook.xlsx

The script is intentionally simple — it only parses the
``01_INDEX`` sheet (one row per (domain, subdomain) pair). Each
domain becomes a pack with display name, intake aliases, subdomain
labels, and a keyword set mined from the workbook's notes column.

If the workbook grows new structured fields (per-domain field
tables, value rules), extend this script to ingest them — don't
hand-edit the output YAML.
"""
from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable

import openpyxl
import yaml


# Words that frequently appear in workbook notes but contribute no
# routing signal. Conservative — we'd rather keep a marginal token
# than drop a discriminating one.
STOP: frozenset[str] = frozenset({
    "the", "and", "or", "of", "for", "to", "a", "an", "in", "on", "with",
    "is", "are", "by", "this", "that", "be", "as", "from", "vs", "vs.",
    "scope", "schema", "all", "any", "etc", "what", "should", "if",
    "include", "includes", "type", "types", "list", "level", "model",
    "data", "open", "close", "back", "index", "id", "ids", "each",
    "given", "see", "new", "old", "use", "using", "fill", "into",
    "complete", "items", "project", "v2", "v4",
})
WORD = re.compile(r"[a-z][a-z0-9_]{2,}")
MAX_KEYWORDS_PER_PACK = 30


def keywords_from_notes(blobs: Iterable[str]) -> list[str]:
    """Frequency-rank tokens from notes text, dropping stop words."""
    counts: dict[str, int] = {}
    for blob in blobs:
        for w in WORD.findall(blob.lower()):
            if w in STOP:
                continue
            counts[w] = counts.get(w, 0) + 1
    return [
        w
        for w, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ][:MAX_KEYWORDS_PER_PACK]


def build_registry(workbook_path: Path) -> dict:
    wb = openpyxl.load_workbook(str(workbook_path), data_only=True)
    ws = wb["01_INDEX"]

    reg: dict[str, dict] = defaultdict(
        lambda: {
            "display_name": "",
            "intake_aliases": set(),
            "subdomain_labels": [],
            "_notes": [],
        }
    )

    for r, row in enumerate(ws.iter_rows(values_only=True)):
        if r < 5:
            continue
        domain, subdomain, did, _, alias, notes = (row + (None,) * 6)[:6]
        if not did or not str(did).strip():
            continue
        did_s = str(did).strip()
        slot = reg[did_s]
        if not slot["display_name"] and domain:
            slot["display_name"] = str(domain).strip()
        if subdomain:
            slot["subdomain_labels"].append(str(subdomain).strip())
            slot["_notes"].append(str(subdomain))
        if notes:
            slot["_notes"].append(str(notes))
        if alias:
            for a in str(alias).split("/"):
                a = a.strip()
                if a:
                    slot["intake_aliases"].add(a)

    out_packs: list[dict] = []
    for did in sorted(reg.keys()):
        info = reg[did]
        out_packs.append(
            {
                "id": did,
                "display_name": info["display_name"] or did,
                "intake_aliases": sorted(info["intake_aliases"]),
                "subdomain_labels": info["subdomain_labels"],
                "keywords": keywords_from_notes(info["_notes"]),
            }
        )

    return {
        "_doc": (
            "OrbitBrief domain pack registry. Source of truth: AWESOME_CHASE "
            "intake workbook v4. Regenerate via tools/extract_domain_packs.py."
        ),
        "version": "v4",
        "packs": out_packs,
    }


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(
            "usage: python tools/extract_domain_packs.py <workbook.xlsx>",
            file=sys.stderr,
        )
        return 2
    src = Path(argv[1])
    if not src.is_file():
        print(f"workbook not found: {src}", file=sys.stderr)
        return 1
    out = (
        Path(__file__).resolve().parent.parent
        / "src"
        / "orbitbrief_core"
        / "world_model"
        / "data"
        / "domain_packs.yaml"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    doc = build_registry(src)
    out.write_text(
        yaml.safe_dump(doc, sort_keys=False, width=120, allow_unicode=True),
        encoding="utf-8",
    )
    print(f"wrote {out} ({len(doc['packs'])} packs, {out.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv))
