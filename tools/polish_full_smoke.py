"""One-shot script: polish a full OPTBOT-shaped set of raw OrbitBrief text
through qwen3:14b on Mac Studio and dump the raw→polished pairs as JSON.

Used to regenerate the handoff bundle mockups with REAL polished output
rather than my invented prose. Run once; the polish cache then makes
subsequent runs free.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from orbitbrief_core.inference.client import OpenAIChatClient
from orbitbrief_core.pm_handoff.polish import (
    PolishCache,
    PolishItem,
    _hash_item,
    polish_items,
)

OLLAMA = "http://100.114.102.122:11434"
MODEL = "qwen3:14b"
CACHE = Path("polish_smoke_cache.jsonl")

# Real-shaped raw OrbitBrief text. Every dollar amount is an actual string
# (not a PowerShell variable). These are the strings that `build_pm_handoff`
# would produce on the OPTBOT case before polish.
RAW = [
    # ───── Gap messages ─────
    ("gap.message", "R-WIFI-001",
     "Controller deployment topology unresolved for site Airport Logistics Annex; bill-of-materials sensitivity is approximately $18,500 depending on whether the site receives a dedicated WLC9800 or shares the ATL-HQ controller."),
    ("gap.message", "R-WIFI-014",
     "No predictive RF survey on file for any site. Access-point counts of 52, 27, and 18 are vendor-quoted but not validated by Ekahau or iBwave heatmap output."),
    ("gap.message", "R-PWR-006",
     "PoE budget at ATL-West appears undersized for 27 Cisco C9166D1 access points operating at full 30W power; existing three Catalyst 9300-48UXM switches each have 90W of PoE headroom."),
    ("gap.message", "R-COMM-002",
     "Net payment terms contradict between source documents: the RFP specifies Net-30 while the signed quote specifies Net-45."),
    ("gap.message", "R-ACCESS-009",
     "Site access window for Airport Logistics Annex is unconfirmed. TSA badging adds 5 to 7 business days lead time per technician."),
    ("gap.message", "R-CUT-003",
     "Cutover window restricted to after 18:00 ET per Priya Narang's clarification email; confirm holiday blackouts."),
    ("gap.message", "R-PROC-011",
     "Cisco C9166D1 lead time 6 to 8 weeks at quoted volume. Order PO must clear by 2026-05-30 to hit cutover."),
    ("gap.message", "R-CAM-002",
     "VMS license count of 16 does not match camera count of 24. Possibly intentional (only 16 priority cameras licensed); confirm."),
    ("gap.message", "R-COMP-001",
     "HIPAA flag detected in Airport Annex (medical kiosk). PCI flag detected in retail concourse. Routing to legal."),
    ("gap.message", "R-SUB-003",
     "Electrical work at ATL-West likely needs licensed electrician for 480V switchgear feed. Need sub procurement timeline."),
    ("gap.message", "R-SLA-001",
     "Customer SLA template references 99.95% uptime; Purtera standard is 99.5%. Penalty schedule unclear."),
    ("gap.message", "R-ADOPT-002",
     "DNA Spaces opt-in approved verbally in kickoff but not in writing. Add to SOW or pull from BOM."),

    # ───── Gap suggested_open_question ─────
    ("gap.question", "R-WIFI-001",
     "Confirm whether Airport Logistics Annex requires a dedicated WLC9800 or will use ATL-HQ controller; BOM sensitivity is $18,500."),
    ("gap.question", "R-WIFI-014",
     "Confirm whether a predictive RF survey (Ekahau or iBwave) has been performed for the affected sites; if not, recommend running one before AP order."),
    ("gap.question", "R-PWR-006",
     "Confirm switch model and current PoE budget allocation at ATL-West; 27 APs at full 30W may exceed available headroom."),
    ("gap.question", "R-COMM-002",
     "Which net payment terms govern this engagement: Net-30 per RFP or Net-45 per signed quote?"),
    ("gap.question", "R-ACCESS-009",
     "What is the TSA badging timeline for technicians at Airport Logistics Annex? Purtera needs 14 days notice."),

    # ───── Risk descriptions ─────
    ("risk.description", "RSK-001",
     "PoE budget at ATL-West may be undersized for the proposed 27 access points at full load; aggregate AP power demand exceeds combined switch PoE headroom."),
    ("risk.description", "RSK-002",
     "TSA badging for Airport Logistics Annex technicians adds 14 days of lead time, threatening the 2026-08-14 board demonstration commitment."),
    ("risk.description", "RSK-003",
     "Cisco C9166D1 quoted lead time of 6 to 8 weeks is aggressive against the planned cutover window."),
    ("risk.description", "RSK-004",
     "VMS license count of 16 conflicts with camera count of 24 in the bill of materials versus SOW exhibit."),
    ("risk.description", "RSK-005",
     "HIPAA and PCI regulated workloads coexist on the Airport Annex shared infrastructure; legal review required before SOW lock."),

    # ───── Risk mitigations ─────
    ("risk.mitigation", "RSK-001",
     "Add switch upgrades to the bill of materials at approximately $22,000 or constrain access-point power profile to high efficiency mode."),
    ("risk.mitigation", "RSK-002",
     "Initiate TSA badging application immediately upon PO receipt; cross-train two ATL-HQ technicians as backup coverage."),
    ("risk.mitigation", "RSK-003",
     "Place PO no later than 2026-05-30; pre-stage 30 percent of inventory at ATL-HQ to de-risk lead time slippage."),
    ("risk.mitigation", "RSK-004",
     "Confirm with security lead which 16 cameras are licensed; the 8 unlicensed cameras may be evidence-only."),
    ("risk.mitigation", "RSK-005",
     "Route to legal for review before SOW lock; assess whether separate VRFs are required for HIPAA and PCI segmentation."),

    # ───── Executive summary ─────
    ("exec.headline", "optbot",
     "OPTBOT_Atlanta_Office_Refresh_Mock_Deal: deal worth $1,847,250 across 3 confirmed site(s) covering Security camera / VMS, Sites / facilities, Commercial terms."),
    ("exec.health_line", "optbot",
     "Status is RED: 5 blocker(s) and 7 warning(s) need PM resolution before SOW lock."),
    ("exec.next_action", "optbot",
     "Resolve the blocker checklist below and confirm the customer clarifications email starter. Do not publish a SOW until blockers clear."),

    # ───── Customer-answer slot questions ─────
    ("answer_slot.question", "R-WIFI-001",
     "For the Airport Logistics Annex site, do you want a dedicated WLC9800 controller or will the site share the ATL-HQ controller? This drives the bill of materials by approximately $18,500."),
    ("answer_slot.question", "R-PWR-006",
     "Could you confirm the current switch model and PoE budget allocation at ATL-West? With 27 access points at full 30W, the existing three Catalyst 9300-48UXM switches at 90W each may be undersized."),
    ("answer_slot.question", "R-COMM-002",
     "We see Net-30 in the RFP and Net-45 in the signed quote. Which net payment term governs the SOW?"),
]


def main() -> None:
    client = OpenAIChatClient(base_url=OLLAMA, timeout_s=180.0)
    cache = PolishCache(path=CACHE)
    items: list[PolishItem] = []
    for role, rid, raw_text in RAW:
        key = _hash_item(f"{role}.{rid}", raw_text, MODEL)
        items.append(
            PolishItem(
                key=key, role=role, raw_text=raw_text, context=f"{role} for {rid}"
            )
        )

    print(f"Polishing {len(items)} items via {MODEL}…")
    t0 = time.monotonic()
    results = polish_items(
        items, chat_client=client, model=MODEL, cache=cache, batch_size=12
    )
    dt = time.monotonic() - t0
    print(f"Done in {dt:.1f}s")

    pairs = []
    for role, rid, raw_text in RAW:
        key = _hash_item(f"{role}.{rid}", raw_text, MODEL)
        r = results.get(key)
        pairs.append(
            {
                "role": role,
                "id": rid,
                "raw": raw_text,
                "polished": r.polished_text if r else raw_text,
                "used_fallback": r.used_fallback if r else True,
            }
        )

    out = {
        "model": MODEL,
        "items_total": len(pairs),
        "items_polished": sum(1 for p in pairs if not p["used_fallback"]),
        "elapsed_s": round(dt, 1),
        "pairs": pairs,
    }
    Path("polish_full_smoke_output.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Wrote polish_full_smoke_output.json — {out['items_polished']}/{out['items_total']} polished")


if __name__ == "__main__":
    main()
