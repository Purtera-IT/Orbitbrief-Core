"""3-judge evaluator for composed briefs (PR 17).

Per case, runs three independent qwen3:14b judges with distinct
system prompts:

  1. evidence_judge — every brief item must cite atom_ids; the cited
     atoms must exist in the envelope; their text must support the
     statement.
  2. coverage_judge — important high-authority atoms (exclusions,
     quantities, customer instructions, assumptions) that didn't
     surface in the brief.
  3. pm_judge — would a senior PM be embarrassed publishing this?
     callouts on tone, precision, hedging, missing pricing references.

Each judge returns a structured JSON verdict; we aggregate into a
per-case ``brief_eval.yaml`` and a corpus-wide
``_brief_eval_summary.yaml``.

Usage::

    python tools/brain_judge_eval.py \\
        --orbit-results /tmp/orbitbrief_core_results_full \\
        --out /tmp/orbitbrief_core_results_full/_brief_eval_summary.yaml \\
        --per-case-out /tmp/orbitbrief_core_results_full \\
        --chat-model qwen3:14b
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

# Make in-tree src importable.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from orbitbrief_core.inference.client import (  # noqa: E402
    ChatMessage,
    OpenAIChatClient,
)


_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def _strip_think(text: str) -> str:
    if "</think>" in text:
        text = text.rsplit("</think>", 1)[1]
    return _THINK_RE.sub("", text).strip()


def _extract_json(text: str) -> dict | None:
    """Robust JSON salvager. Tries:
    1) the whole reply
    2) a fenced ```json``` block
    3) the largest balanced {...} substring
    4) progressively trims trailing prose until json.loads succeeds
    """
    text = _strip_think(text).strip()
    if not text:
        return None
    # 1) whole reply
    try:
        return json.loads(text)
    except Exception:
        pass
    # 2) fenced code block
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    # 3) balanced-brace scan — find the largest {...} that parses
    starts = [i for i, c in enumerate(text) if c == "{"]
    ends = [i for i, c in enumerate(text) if c == "}"]
    for s in starts:
        for e in reversed(ends):
            if e <= s:
                continue
            candidate = text[s : e + 1]
            try:
                return json.loads(candidate)
            except Exception:
                continue
    return None


# ────────────────────────────── judge prompts ─────────────────────────


_EVIDENCE_SYS = """\
/no_think
You are the OrbitBrief EVIDENCE JUDGE.

Given a composed brief and the supporting envelope (atoms with
text + locator), score whether every brief item is grounded.

For each brief item with a non-empty `supporting_atom_ids`, check:
  * each cited atom_id exists in the envelope
  * the atom's text is consistent with the item's `statement`

Output ONLY JSON, no prose, no <think>:

{
  "items_total": <int>,
  "items_with_atom_citations": <int>,
  "items_with_packet_citations_only": <int>,
  "items_with_no_citations": <int>,
  "unsupported_claims": [
    {"item_id": "<id>", "statement": "<short quote>", "reason": "<why>"}
  ],
  "verdict": "GREEN" | "YELLOW" | "RED"
}

Verdict rules:
  RED if any unsupported_claims OR items_with_no_citations > 0
  YELLOW if items_with_packet_citations_only > items_with_atom_citations
  GREEN otherwise
"""

_COVERAGE_SYS = """\
/no_think
You are the OrbitBrief COVERAGE JUDGE.

Given a list of HIGH-AUTHORITY atoms (customer_current_authored,
approved_site_roster, vendor_quote) of types {exclusion, quantity,
customer_instruction, assumption} and the composed brief items,
identify atoms that should have surfaced in the brief but did not.

Output ONLY JSON, no prose, no <think>:

{
  "high_authority_atoms_total": <int>,
  "high_authority_atoms_in_brief": <int>,
  "missed_blocker_exclusions": [
    {"atom_id": "<id>", "text": "<short quote>"}
  ],
  "missed_blocker_quantities": [
    {"atom_id": "<id>", "text": "<short quote>"}
  ],
  "missed_blocker_assumptions": [
    {"atom_id": "<id>", "text": "<short quote>"}
  ],
  "verdict": "GREEN" | "YELLOW" | "RED"
}

Verdict rules:
  RED if any missed_blocker_exclusions
  YELLOW if any missed_blocker_quantities or missed_blocker_assumptions
  GREEN otherwise
"""

_PM_SYS = """\
/no_think
You are the OrbitBrief SENIOR PM JUDGE.

Given a composed brief, judge whether a senior project manager would
be embarrassed publishing it as-is. Look for:
  - generic boilerplate where SKUs / vendor names / quantities exist
  - hedge phrases ("possibly", "TBD", "to be determined") that should
    have been resolved by the substrate
  - tone / precision issues (passive voice, unclear ownership)
  - missing pricing references when vendor_line_item atoms exist
  - sections that say "see appendix" without an appendix

Output ONLY JSON, no prose, no <think>:

{
  "embarrassment_signals": [
    {"section": "<name>", "signal": "<one-line description>"}
  ],
  "would_pm_publish": true | false,
  "verdict": "GREEN" | "YELLOW" | "RED"
}

Verdict rules:
  RED if would_pm_publish=false
  YELLOW if 1-3 embarrassment_signals
  GREEN if 0 embarrassment_signals
"""


# ────────────────────────────── data assembly ─────────────────────────


def _load_json(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8"))


def _candidate(case_dir: Path, *names: str) -> Path | None:
    for n in names:
        p = case_dir / n
        if p.is_file():
            return p
    return None


def _flatten_brief_items(composed_brief: dict) -> list[dict]:
    out: list[dict] = []
    for grp in (
        composed_brief.get("domains")
        or composed_brief.get("domain_groups")
        or []
    ):
        pack_id = grp.get("pack_id") or grp.get("display_name") or ""
        for sec in grp.get("sections") or []:
            sec_id = sec.get("section_id") or sec.get("section") or ""
            for it in sec.get("items") or []:
                out.append(
                    {
                        "id": it.get("item_id"),
                        "pack": pack_id,
                        "section": sec_id,
                        "statement": it.get("statement"),
                        "supporting_atom_ids": list(
                            it.get("supporting_atom_ids") or ()
                        ),
                        "supporting_packet_ids": list(
                            it.get("supporting_packet_ids") or ()
                        ),
                    }
                )
    return out


def _high_authority_focus(envelope: dict) -> list[dict]:
    focus_types = {"exclusion", "quantity", "customer_instruction", "assumption"}
    out: list[dict] = []
    for a in envelope.get("atoms") or []:
        if a.get("authority_class") not in {
            "customer_current_authored", "approved_site_roster", "vendor_quote",
        }:
            continue
        if a.get("atom_type") not in focus_types:
            continue
        out.append(
            {
                "atom_id": a.get("id"),
                "atom_type": a.get("atom_type"),
                "authority_class": a.get("authority_class"),
                "text": (a.get("text") or "")[:280],
            }
        )
    # Cap at 60 to keep prompts small.
    return out[:60]


def _atoms_index(envelope: dict, ids: set[str]) -> list[dict]:
    out = []
    for a in envelope.get("atoms") or []:
        aid = a.get("id")
        if aid in ids:
            out.append({"atom_id": aid, "text": (a.get("text") or "")[:280]})
    return out


# ────────────────────────────── judge driver ──────────────────────────


def _ask_judge(
    chat: ChatClient,
    sys_prompt: str,
    user_payload: str,
    *,
    model: str,
    timeout_s: int = 240,
    max_tokens: int = 2048,
) -> dict | None:
    try:
        reply = chat.complete(
            [ChatMessage("system", sys_prompt), ChatMessage("user", user_payload)],
            model=model,
            temperature=0.0,
            max_tokens=max_tokens,
        )
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}
    return _extract_json(reply) or {"error": "judge returned no parsable JSON"}


def _evaluate_case(
    case_dir: Path, *, chat: ChatClient, model: str
) -> dict | None:
    envelope_p = _candidate(case_dir, "00_envelope.json")
    composed_p = _candidate(case_dir, "80_composed_brief.json", "composed_brief.json")
    if envelope_p is None or composed_p is None:
        return {
            "case_id": case_dir.name,
            "status": "skipped",
            "reason": (
                "missing envelope" if envelope_p is None else "no composed_brief — brain run not present"
            ),
        }
    envelope = _load_json(envelope_p)
    composed = _load_json(composed_p)
    items = _flatten_brief_items(composed)
    cited_atom_ids = set()
    for it in items:
        cited_atom_ids.update(it["supporting_atom_ids"])
    cited_atoms = _atoms_index(envelope, cited_atom_ids)
    focus_atoms = _high_authority_focus(envelope)

    # Tight payloads — judges only need the relevant slices.
    evidence_payload = json.dumps(
        {
            "items": items,
            "cited_atoms": cited_atoms[:80],  # cap
        },
        ensure_ascii=False,
    )[:24000]

    coverage_payload = json.dumps(
        {
            "items": [
                {
                    "id": it["id"],
                    "section": it["section"],
                    "statement": it["statement"],
                    "supporting_atom_ids": it["supporting_atom_ids"],
                }
                for it in items
            ],
            "high_authority_focus_atoms": focus_atoms,
        },
        ensure_ascii=False,
    )[:24000]

    pm_payload = json.dumps(
        {
            "executive_summary": composed.get("summary") or composed.get("executive_summary"),
            "domains": [
                {
                    "pack": g.get("pack_id") or g.get("display_name"),
                    "sections": [
                        {
                            "section": s.get("section_id") or s.get("section"),
                            "items": [
                                (it.get("statement") or "")[:300]
                                for it in (s.get("items") or [])
                            ],
                        }
                        for s in (g.get("sections") or [])
                    ],
                }
                for g in (composed.get("domains") or composed.get("domain_groups") or [])
            ],
        },
        ensure_ascii=False,
    )[:24000]

    verdicts = {
        "case_id": case_dir.name,
        "status": "ok",
        "judges": {
            "evidence": _ask_judge(chat, _EVIDENCE_SYS, evidence_payload, model=model),
            "coverage": _ask_judge(chat, _COVERAGE_SYS, coverage_payload, model=model),
            "pm": _ask_judge(chat, _PM_SYS, pm_payload, model=model),
        },
    }
    # Aggregate verdict — the worst of the three.
    rank = {"GREEN": 0, "YELLOW": 1, "RED": 2}
    worst = "GREEN"
    for j in verdicts["judges"].values():
        if not isinstance(j, dict):
            continue
        v = j.get("verdict") if isinstance(j, dict) else None
        if v in rank and rank[v] > rank[worst]:
            worst = v
        if "error" in (j or {}):
            worst = "RED"
    verdicts["aggregate_verdict"] = worst
    return verdicts


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--orbit-results", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--per-case-out", type=Path, default=None)
    p.add_argument("--chat-model", default="qwen3:14b")
    p.add_argument("--ollama-host", default="http://localhost:11434")
    args = p.parse_args(argv)

    chat = OpenAIChatClient(base_url=args.ollama_host, timeout_s=600.0)

    cases = sorted(x for x in args.orbit_results.iterdir() if x.is_dir())
    per_case: list[dict] = []
    for case in cases:
        verdict = _evaluate_case(case, chat=chat, model=args.chat_model)
        if verdict is None:
            continue
        per_case.append(verdict)
        if args.per_case_out is not None:
            out = args.per_case_out / case.name / "brief_eval.yaml"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(yaml.safe_dump(verdict, sort_keys=False), encoding="utf-8")
        print(
            f"  [{verdict.get('aggregate_verdict','SKIP'):6s}] {case.name}",
            file=sys.stderr,
        )

    from collections import Counter
    by_verdict = Counter(v.get("aggregate_verdict", "SKIP") for v in per_case)
    summary = {
        "brief_eval_summary": {
            "cases_evaluated": sum(1 for v in per_case if v.get("status") == "ok"),
            "cases_skipped": sum(1 for v in per_case if v.get("status") != "ok"),
            "by_verdict": dict(by_verdict),
        },
        "per_case": per_case,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(yaml.safe_dump(summary, sort_keys=False), encoding="utf-8")
    print(f"\nwrote brief eval summary → {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
