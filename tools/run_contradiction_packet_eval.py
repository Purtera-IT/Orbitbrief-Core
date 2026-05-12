from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from orbitbrief_core.parser.site_schematic.contradiction_eval import (
    build_contradiction_manifest_template,
    load_contradiction_packet_registry,
    run_contradiction_packet_registry_eval,
    summarize_contradiction_packet_activation,
    summarize_contradiction_packet_registry,
    validate_contradiction_packet_registry,
)


def _default_registry() -> Path:
    return Path("tests/site_schematic/fixtures/contradiction_packet_registry.json")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def cmd_validate(args: argparse.Namespace) -> int:
    registry_path = Path(args.registry)
    registry = load_contradiction_packet_registry(registry_path)
    errors = validate_contradiction_packet_registry(registry)
    summary = summarize_contradiction_packet_registry(registry=registry, registry_base_dir=registry_path.parent)
    payload = {
        "registry_path": str(registry_path),
        "valid": not errors and not summary.get("manifest_validation_errors"),
        "registry_errors": errors,
        "summary": summary,
    }
    if args.output:
        _write_json(Path(args.output), payload)
    print(json.dumps(payload, indent=2))
    return 0 if payload["valid"] else 1


def cmd_eval(args: argparse.Namespace) -> int:
    registry_path = Path(args.registry)
    registry = load_contradiction_packet_registry(registry_path)
    selected = [row.strip() for row in (args.packet_id or []) if row.strip()]
    payload = run_contradiction_packet_registry_eval(
        registry=registry,
        registry_base_dir=registry_path.parent,
        selected_packet_ids=selected or None,
    )
    if args.output:
        _write_json(Path(args.output), payload)
    print(json.dumps(payload, indent=2))
    return 0


def cmd_activate(args: argparse.Namespace) -> int:
    registry_path = Path(args.registry)
    registry = load_contradiction_packet_registry(registry_path)
    selected = [row.strip() for row in (args.packet_id or []) if row.strip()]
    base_payload = run_contradiction_packet_registry_eval(
        registry=registry,
        registry_base_dir=registry_path.parent,
        selected_packet_ids=selected or None,
    )
    packet_reports = list(base_payload.get("packet_reports", []))
    for row in packet_reports:
        packet_id = str(row.get("packet_id", "")).strip()
        if not packet_id:
            continue
        if selected and packet_id not in selected:
            continue
        if args.output_dir:
            output_path = Path(args.output_dir) / f"contradiction_packet_activation_{packet_id}.json"
            _write_json(output_path, row if isinstance(row, dict) else {"packet_id": packet_id, "report": row})
    payload = {
        "kpi_view": "contradiction_packet_activation",
        "registry_path": str(registry_path),
        "selected_packet_ids": selected,
        "registry_summary": summarize_contradiction_packet_registry(registry=registry, registry_base_dir=registry_path.parent),
        "activation_summary": summarize_contradiction_packet_activation(packet_reports),
        "packet_reports": packet_reports,
    }
    if args.output:
        _write_json(Path(args.output), payload)
    print(json.dumps(payload, indent=2))
    return 0


def cmd_template(args: argparse.Namespace) -> int:
    payload = build_contradiction_manifest_template(
        packet_id=args.packet_id,
        packet_label=args.packet_label,
        packet_level_expected=args.packet_level_expected,
        packet_type=args.packet_type,
    )
    if args.output:
        _write_json(Path(args.output), payload)
    print(json.dumps(payload, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run contradiction packet registry onboarding and eval.")
    sub = parser.add_subparsers(dest="command", required=True)

    validate_parser = sub.add_parser("validate", help="Validate contradiction registry + manifests.")
    validate_parser.add_argument("--registry", default=str(_default_registry()))
    validate_parser.add_argument("--output", default="")
    validate_parser.set_defaults(func=cmd_validate)

    eval_parser = sub.add_parser("eval", help="Run contradiction eval for registry packets.")
    eval_parser.add_argument("--registry", default=str(_default_registry()))
    eval_parser.add_argument("--packet-id", action="append", default=[], help="Evaluate only selected packet id(s).")
    eval_parser.add_argument("--output", default="")
    eval_parser.set_defaults(func=cmd_eval)

    activate_parser = sub.add_parser(
        "activate",
        help="Run packet-by-packet activation checks and emit per-packet reports.",
    )
    activate_parser.add_argument("--registry", default=str(_default_registry()))
    activate_parser.add_argument("--packet-id", action="append", default=[], help="Activate/evaluate only selected packet id(s).")
    activate_parser.add_argument("--output-dir", default="compiled_artifacts/site_schematic_symbol_detector_phase")
    activate_parser.add_argument("--output", default="")
    activate_parser.set_defaults(func=cmd_activate)

    template_parser = sub.add_parser("template", help="Generate contradiction manifest template.")
    template_parser.add_argument("--packet-id", required=True)
    template_parser.add_argument("--packet-label", required=True)
    template_parser.add_argument("--packet-level-expected", default="high_priority_review")
    template_parser.add_argument("--packet-type", default="detail_installation_conflict")
    template_parser.add_argument("--output", default="")
    template_parser.set_defaults(func=cmd_template)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

