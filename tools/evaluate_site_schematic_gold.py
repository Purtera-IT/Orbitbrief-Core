from __future__ import annotations

import argparse
import json
from pathlib import Path

from tests.site_schematic.gold_eval import (
    LOW_VOLTAGE_FIXTURE,
    WIRELESS_FIXTURE,
    build_gold_scorecard,
    build_pdf_bundle,
    load_gold_fixture,
    resolve_fixture_pdf,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate site-schematic parser output against gold route fixtures.")
    parser.add_argument("--wireless-pdf", type=Path, default=resolve_fixture_pdf('wireless'))
    parser.add_argument("--low-voltage-pdf", type=Path, default=resolve_fixture_pdf('low_voltage'))
    parser.add_argument("--output", type=Path, default=None, help="Optional path to write JSON scorecards.")
    args = parser.parse_args()

    scorecards: dict[str, dict] = {}
    if args.wireless_pdf.exists():
        bundle = build_pdf_bundle(args.wireless_pdf)
        scorecards["wireless"] = build_gold_scorecard(bundle, load_gold_fixture(WIRELESS_FIXTURE)).to_dict()
    if args.low_voltage_pdf.exists():
        bundle = build_pdf_bundle(args.low_voltage_pdf)
        scorecards["low_voltage"] = build_gold_scorecard(bundle, load_gold_fixture(LOW_VOLTAGE_FIXTURE)).to_dict()

    payload = json.dumps(scorecards, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
