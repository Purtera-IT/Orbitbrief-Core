from __future__ import annotations

import argparse
import json
from pathlib import Path

from orbitbrief_core.compiler.packs.professional_services_text.compiler_runner import load_compiled_pack
from orbitbrief_core.parser.router import RouterInput
from orbitbrief_core.parser.runtime import parse_and_packetize


def _read_preview(path: Path) -> str:
    if path.suffix.lower() in {".txt", ".md", ".eml"}:
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return path.read_text(encoding="utf-8", errors="replace")
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Route and parse a single artifact into DocumentParse.")
    parser.add_argument("--pack-id", default="professional_services_text")
    parser.add_argument("--compiled-root", default="compiled_artifacts")
    parser.add_argument("--pack-version", default="v1")
    parser.add_argument("--doc-id", default="smoke_doc")
    parser.add_argument("--input-path", required=True)
    parser.add_argument("--mime-type", default=None)
    parser.add_argument("--metadata-json", default="{}", help="Optional JSON object merged into RouterInput.metadata")
    args = parser.parse_args()

    input_path = Path(args.input_path).resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"Input artifact does not exist: {input_path}")

    compiled_pack = load_compiled_pack(
        args.pack_id,
        compiled_root=Path(args.compiled_root).resolve(),
        pack_version=args.pack_version,
    )
    metadata = json.loads(args.metadata_json)
    if not isinstance(metadata, dict):
        raise ValueError("--metadata-json must be a JSON object")
    metadata["path"] = str(input_path)

    router_input = RouterInput(
        doc_id=args.doc_id,
        filename=str(input_path),
        mime_type=args.mime_type,
        raw_text_preview=_read_preview(input_path),
        metadata=metadata,
    )
    runtime_result = parse_and_packetize(router_input=router_input, compiled_pack=compiled_pack)
    parse_plan = runtime_result.parse_plan
    document_parse = runtime_result.document_parse

    print(f"doc_id: {document_parse.doc_id}")
    print(f"adapter: {parse_plan.adapter_chain[0] if parse_plan.adapter_chain else '<none>'}")
    print(f"parser_profile_id: {parse_plan.parser_profile_id}")
    print(f"modality: {document_parse.modality}")
    print(f"spans: {len(document_parse.evidence_spans)}")
    print(f"packets: {len(runtime_result.packet_candidates)}")
    print(f"review_flags: {len(document_parse.review_flags)}")
    print(f"sections: {len(document_parse.section_tree.nodes)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
