#!/usr/bin/env python3
"""Phase-1.5 envelope backfill: LLM-assisted entity extraction.

Sits between parser-os (regex / pattern extraction, LLM-free) and
Orbitbrief-Core (LLM synthesis, must cite atoms). The job is to scan
the raw_text of every atom in a parser-os envelope and surface
entities the regex pipeline couldn't catch:

  * Written-out money amounts ("five million dollars",
    "two hundred fifty thousand")
  * Pronoun-resolved stakeholders ("she approves", "they own X")
  * Implicit / relative dates ("30 days after kickoff",
    "Q3 deliverable", "next Monday")
  * Site / vendor / product names that look ambiguous to regex

Output is an enriched envelope (same v2 schema) with:

  * Additional atoms of atom_type=entity carrying the new entity_keys
  * SourceRef provenance pointing back to the original source atom
  * entity_keys index updated with the new keys

The original parser-os atoms are preserved unchanged. Orbitbrief-Core's
strict "must cite an atom_id" contract is still satisfied because every
new atom is a real atom in the envelope.

Usage:

    python tools/envelope_backfill.py \\
        /path/to/envelope.json \\
        --out /path/to/envelope_enriched.json \\
        --ollama-base-url http://localhost:11434 \\
        --model qwen3:14b
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

# Make Orbitbrief-Core's inference client importable from a checkout.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from orbitbrief_core.inference.client import ChatMessage, OpenAIChatClient

# ─── Configuration ───

# Atoms shorter than this are usually structural (headers, table cells)
# and unlikely to contain backfill-worthy free-text entities.
_MIN_RAW_TEXT_LEN = 40

# Atom types we scan for backfill. These are the ones with free-text
# narrative content. ``quantity`` / ``entity`` atoms are usually
# already structured by parser-os.
_BACKFILL_ATOM_TYPES = frozenset({
    "scope_item",
    "constraint",
    "exclusion",
    "decision",
    "risk",
    "assumption",
    "open_question",
    "action_item",
    "meeting_commitment",
    "customer_instruction",
    "compliance",
    "vendor_line_item",
})

# Hard cap on raw_text we send to the LLM per atom — keeps prompt
# budget predictable. Most useful entity context lives in the first
# few hundred chars.
_MAX_RAW_TEXT_CHARS = 1200

# Hard cap on atoms scanned per run (cost / latency guard).
# Configurable via --max-atoms.
_DEFAULT_MAX_ATOMS = 500

# Entity types the backfill layer can emit. Matches parser-os v3
# entity_type namespace conventions.
_VALID_ENTITY_TYPES = frozenset({
    "money", "stakeholder", "date", "milestone", "site",
    "vendor", "customer", "device", "service",
})


_SYSTEM_PROMPT = """You are an entity-extraction backfill agent for a deal-document pipeline.

Given a passage from a deal document, identify entities a regex-based extractor missed
and emit them as structured JSON.

Focus on:
- MONEY: written-out amounts ("five million dollars", "two hundred thousand"),
  multi-currency mentions ("equivalent to USD 500K"), allowance-style amounts.
- STAKEHOLDER: named approvers/owners when a pronoun ("she", "he", "they") refers
  to a person whose name appears in context. Also titled approvers without
  surname when context disambiguates ("the CFO approves" → only emit if CFO has
  a named referent in scope).
- DATE: implicit / relative dates ("30 days after kickoff", "next Monday",
  "the week of June 17"), fiscal references not already in ISO form.
- MILESTONE: dated project milestones / events the regex extractor couldn't
  detect (events with cues like "kickoff", "cutover", "go-live", "blackout",
  "phase complete", "hypercare end" + a date reference).
- SITE: physical-place names the regex extractor missed (lowercase prose like
  "Atlanta staging facility" / "downtown distribution center" that don't have
  fully-capitalized title-case).
- VENDOR: vendor / supplier names mentioned in business context that aren't
  in the standard cross-pack vendor list.

Hard rules:
1. Output MUST be valid JSON: {"new_entities": [{...}, ...]}. NO prose, no markdown.
2. DO NOT repeat entities already in the existing_entity_keys list.
3. DO NOT extract things the regex extractor obviously catches: standard
   dollar amounts ($1,847,250), ISO dates (2026-07-31), "First Last" names
   with role context in the same sentence.
4. Each entity must have:
   - "entity_type": one of money | stakeholder | date | milestone | site | vendor | customer
   - "canonical_value": normalized form (see below)
   - "raw_text_span": exact text span from the input that supports this
   - "confidence": float 0.0-1.0 (only emit ≥ 0.7 confidence)
   - "rationale": one short sentence why this is a real entity
5. Normalization:
   - money: absolute integer dollars (1.5 million → 1500000)
   - date / milestone: ISO YYYY-MM-DD; if year ambiguous, ONLY emit when
     the doc context disambiguates it
   - stakeholder: first_last lowercase slug
   - site / vendor / customer: lowercase slug, underscores for spaces
6. If the passage has nothing new to add, return {"new_entities": []}.
7. If unsure about a candidate, SKIP it. False positives cost more than misses.

/no_think"""


def _build_user_message(
    *, raw_text: str, existing_entity_keys: list[str], atom_id: str, atom_type: str,
) -> str:
    """Render the user-message JSON-ish for a single atom."""
    existing_summary = ", ".join(sorted(set(existing_entity_keys))[:30]) or "(none)"
    return (
        f'atom_id: "{atom_id}"\n'
        f"atom_type: {atom_type}\n"
        f"existing_entity_keys: [{existing_summary}]\n"
        f"raw_text:\n"
        f'"""\n{raw_text[:_MAX_RAW_TEXT_CHARS]}\n"""'
    )


def _extract_json(text: str) -> dict[str, Any]:
    """Tolerant JSON extractor for qwen3 output.

    Qwen3 with /no_think still emits ~110 tokens of empty <think>
    markers before the JSON. We strip those and look for the
    outermost ``{...}`` block.
    """
    # Strip qwen3 think markers
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    # Find the first balanced JSON object
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start != -1:
                candidate = text[start : i + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    start = -1
                    continue
    return {"new_entities": []}


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _canonical_key(entity_type: str, canonical_value: str) -> str | None:
    """Build a canonical key from the LLM's output. Returns None if
    the value can't be normalized."""
    val = canonical_value.strip()
    if not val:
        return None
    if entity_type == "money":
        # Strip currency / commas / dollar signs, parse integer
        cleaned = re.sub(r"[^\d.]", "", val)
        try:
            num = float(cleaned)
        except ValueError:
            return None
        if num < 100 or num > 1_000_000_000_000:
            return None
        return f"money:{int(num) if num == int(num) else round(num, 2)}"
    if entity_type in {"date", "milestone"}:
        # Expect ISO YYYY-MM-DD
        m = re.match(r"^(20[2-9][0-9])-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$", val)
        if not m:
            return None
        return f"{entity_type}:{val}"
    if entity_type in {"stakeholder", "site", "vendor", "customer", "device", "service"}:
        slug = _slugify(val)
        if slug and len(slug) >= 3:
            return f"{entity_type}:{slug}"
    return None


def _stable_id(prefix: str, *parts: str) -> str:
    h = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{h}"


_WS_NORM_RE = re.compile(r"\s+")


def _verify_span(span: str, source: str, *, min_len: int = 8) -> bool:
    """D2 hallucination guard: does ``span`` actually appear in ``source``?

    Whitespace-collapsed, case-folded substring match. Empty or
    trivially-short spans (<8 chars after normalization) are kept
    because the LLM sometimes quotes a single word that's still
    faithful — verifying every micro-span creates too many false
    drops. Real hallucinations tend to be paragraph-shaped.
    """
    if not span:
        return True
    norm_span = _WS_NORM_RE.sub(" ", span).strip().lower()
    if len(norm_span) < min_len:
        return True
    norm_source = _WS_NORM_RE.sub(" ", source or "").lower()
    return norm_span in norm_source


def _new_atom_from_entity(
    *,
    project_id: str,
    source_atom: dict[str, Any],
    entity_key: str,
    entity_type: str,
    canonical_value: str,
    raw_text_span: str,
    confidence: float,
    rationale: str,
    model: str,
) -> dict[str, Any]:
    """Build a new envelope-projection atom dict for the backfilled entity.

    Schema matches the envelope projection (compact 9-field shape) so it
    drops cleanly into ``envelope.atoms`` and downstream Orbitbrief-Core
    consumers (which all read the projection) treat it as a first-class
    atom.
    """
    src_atom_id = source_atom["id"]
    artifact_id = source_atom["artifact_id"]
    new_id = _stable_id("atm_llm", project_id, src_atom_id, entity_key, model)
    text = (
        f"LLM-backfilled {entity_type}: {canonical_value} "
        f'(from "{raw_text_span[:120]}")'
    )
    # Locator: copy the source atom's locator so replay still
    # traces back to the same page / sheet / row.
    locator = dict(source_atom.get("locator") or {})
    # Annotate the locator with the LLM provenance so consumers can
    # tell a backfilled atom from a regex one without looking elsewhere.
    locator["extracted_via"] = f"llm_backfill::{model}"
    locator["source_atom_id"] = src_atom_id
    locator["llm_rationale"] = rationale[:280]
    locator["llm_raw_text_span"] = raw_text_span[:280]
    return {
        "id": new_id,
        "artifact_id": artifact_id,
        "atom_type": "entity",
        # ``machine_extractor`` is the schema's authority bucket for
        # entities produced by a programmatic extractor (regex, LLM,
        # heuristic). The original parser-os extractor uses the same
        # value, so LLM backfills land in the same authority tier.
        "authority_class": "machine_extractor",
        "confidence": float(confidence),
        "text": text,
        "section_path": list(source_atom.get("section_path") or []),
        "locator": locator,
        # ``unsupported`` matches the schema's ``Verification`` enum;
        # LLM-backfilled atoms have no replayable source-bytes binding
        # because the LLM derived the entity, not the underlying text.
        "verified": "unsupported",
        "entity_keys": [entity_key],
    }


def _atom_text(atom: dict[str, Any]) -> str:
    """Return the atom's free-text content.

    Envelope projection uses ``text``; the underlying EvidenceAtom uses
    ``raw_text``. Try both for forward-compat.
    """
    val = atom.get("text") or atom.get("raw_text") or ""
    if isinstance(val, str):
        return val
    return ""


def _scan_atom(
    *,
    atom: dict[str, Any],
    chat: OpenAIChatClient,
    model: str,
    project_id: str,
    global_keys: set[str],
) -> list[dict[str, Any]]:
    """Send one atom's text to the LLM, parse new entities, build atoms.

    ``global_keys`` is the FULL set of entity_keys seen anywhere in the
    envelope — so the LLM is told the project-level "already extracted"
    list, not just this atom's. Without that, the LLM re-extracts
    sites / vendors / dates that appear elsewhere.
    """
    raw_text = _atom_text(atom)
    if len(raw_text.strip()) < _MIN_RAW_TEXT_LEN:
        return []
    # Per-atom keys + global envelope keys both feed the prompt.
    atom_local_keys = list(atom.get("entity_keys") or [])
    user_msg = _build_user_message(
        raw_text=raw_text,
        existing_entity_keys=sorted(set(atom_local_keys) | global_keys),
        atom_id=atom["id"],
        atom_type=atom.get("atom_type") or "unknown",
    )
    messages = [
        ChatMessage(role="system", content=_SYSTEM_PROMPT),
        ChatMessage(role="user", content=user_msg),
    ]
    try:
        result = chat.complete_with_usage(
            messages,
            model=model,
            temperature=0.0,
            max_tokens=2048,
        )
    except Exception as exc:
        sys.stderr.write(f"  llm error on atom {atom['id']}: {exc}\n")
        return []
    payload = _extract_json(result.text)
    new_entities = payload.get("new_entities") or []
    if not isinstance(new_entities, list):
        return []
    new_atoms: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for ent in new_entities:
        if not isinstance(ent, dict):
            continue
        etype = (ent.get("entity_type") or "").strip().lower()
        if etype not in _VALID_ENTITY_TYPES:
            continue
        canonical_value = str(ent.get("canonical_value") or "").strip()
        if not canonical_value:
            continue
        try:
            confidence = float(ent.get("confidence") or 0)
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence < 0.7:
            continue
        entity_key = _canonical_key(etype, canonical_value)
        if not entity_key:
            continue
        # De-dupe against existing atom keys + earlier backfills + global envelope
        if (entity_key in atom_local_keys
                or entity_key in seen_keys
                or entity_key in global_keys):
            continue
        # D2 hallucination guard: drop findings whose raw_text_span
        # doesn't actually appear in the source atom's text. LLMs
        # sometimes invent plausible-looking spans — those are
        # unverifiable as evidence and dangerous to ship.
        span = str(ent.get("raw_text_span") or "")[:300]
        if not _verify_span(span, raw_text):
            continue
        seen_keys.add(entity_key)
        new_atoms.append(
            _new_atom_from_entity(
                project_id=project_id,
                source_atom=atom,
                entity_key=entity_key,
                entity_type=etype,
                canonical_value=canonical_value,
                raw_text_span=span,
                confidence=confidence,
                rationale=str(ent.get("rationale") or "")[:300],
                model=model,
            )
        )
    return new_atoms


def _enrich_envelope(
    envelope: dict[str, Any],
    *,
    chat: OpenAIChatClient,
    model: str,
    max_atoms: int,
    verbose: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (enriched_envelope, stats)."""
    project_id = envelope.get("project_id", "unknown")
    atoms = envelope.get("atoms") or []
    candidates = [
        a for a in atoms
        if (a.get("atom_type") in _BACKFILL_ATOM_TYPES)
        and len(_atom_text(a)) >= _MIN_RAW_TEXT_LEN
    ]
    candidates = candidates[:max_atoms]
    # Global entity-key set — every key seen anywhere in the envelope.
    # Used to keep the LLM from re-extracting things parser-os already
    # captured in OTHER atoms. The compact envelope projection keeps
    # entity_keys in two places: per-atom (often null after projection)
    # AND on the top-level ``entities`` list (always populated). Pull
    # from both for completeness.
    global_keys: set[str] = set()
    for a in atoms:
        for k in a.get("entity_keys") or []:
            global_keys.add(k)
    for e in envelope.get("entities") or []:
        ck = e.get("canonical_key")
        if ck:
            global_keys.add(ck)
        for alias in e.get("aliases") or []:
            global_keys.add(alias)
    if verbose:
        print(
            f"envelope_backfill: scanning {len(candidates)} atoms "
            f"(of {len(atoms)} total) via {model}; "
            f"existing global entity_keys={len(global_keys)}...",
            file=sys.stderr,
        )
    new_atoms: list[dict[str, Any]] = []
    by_type: Counter[str] = Counter()
    t0 = time.perf_counter()
    for i, atom in enumerate(candidates):
        if verbose and (i + 1) % 10 == 0:
            elapsed = time.perf_counter() - t0
            print(
                f"  [{i + 1}/{len(candidates)}] {len(new_atoms)} new atoms so far "
                f"({elapsed:.1f}s elapsed)",
                file=sys.stderr,
            )
        atoms_from_this = _scan_atom(
            atom=atom, chat=chat, model=model, project_id=project_id,
            global_keys=global_keys,
        )
        for new_atom in atoms_from_this:
            new_atoms.append(new_atom)
            for k in new_atom.get("entity_keys") or []:
                etype = k.split(":", 1)[0] if ":" in k else "unknown"
                by_type[etype] += 1
                # Feed back into the global set so subsequent atoms
                # don't re-extract the same key.
                global_keys.add(k)
    # Build enriched envelope (preserve original structure)
    enriched = dict(envelope)
    enriched["atoms"] = list(atoms) + new_atoms
    # Update summary if present
    summary = dict(enriched.get("summary") or {})
    summary["atom_count"] = len(enriched["atoms"])
    summary["llm_backfill_atom_count"] = len(new_atoms)
    enriched["summary"] = summary
    # Update indexes — but only the ones that exist already. parser-os
    # has indexes.atoms_by_atom_type, atoms_by_entity_key, etc. We
    # update those that touch atom ids.
    indexes = dict(enriched.get("indexes") or {})
    if "atoms_by_atom_type" in indexes:
        ab = dict(indexes["atoms_by_atom_type"])
        ab.setdefault("entity", [])
        ab["entity"] = list(ab["entity"]) + [a["id"] for a in new_atoms]
        indexes["atoms_by_atom_type"] = ab
    if "atoms_by_entity_key" in indexes:
        be = dict(indexes["atoms_by_entity_key"])
        for new_atom in new_atoms:
            for k in new_atom.get("entity_keys") or []:
                be.setdefault(k, [])
                if new_atom["id"] not in be[k]:
                    be[k] = list(be[k]) + [new_atom["id"]]
        indexes["atoms_by_entity_key"] = be
    enriched["indexes"] = indexes
    stats = {
        "scanned_atom_count": len(candidates),
        "total_atom_count_before": len(atoms),
        "total_atom_count_after": len(enriched["atoms"]),
        "new_atom_count": len(new_atoms),
        "new_atoms_by_type": dict(by_type),
        "duration_s": round(time.perf_counter() - t0, 1),
        "model": model,
    }
    return enriched, stats


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="envelope_backfill")
    p.add_argument("envelope", help="parser-os envelope.json path")
    p.add_argument("--out", required=True, help="enriched envelope output path")
    p.add_argument("--ollama-base-url", default="http://localhost:11434")
    p.add_argument("--model", default="qwen3:14b")
    p.add_argument("--max-atoms", type=int, default=_DEFAULT_MAX_ATOMS)
    p.add_argument("--timeout-s", type=float, default=300.0)
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)
    env_path = Path(args.envelope)
    if not env_path.is_file():
        print(f"envelope_backfill: not found: {env_path}", file=sys.stderr)
        return 1
    envelope = json.loads(env_path.read_text(encoding="utf-8"))
    if envelope.get("schema_version") != "orbitbrief.input.v2":
        print(
            f"envelope_backfill: warning — envelope schema is "
            f"{envelope.get('schema_version')!r}; expected orbitbrief.input.v2. "
            f"Proceeding anyway.",
            file=sys.stderr,
        )
    chat = OpenAIChatClient(base_url=args.ollama_base_url, timeout_s=args.timeout_s)
    enriched, stats = _enrich_envelope(
        envelope,
        chat=chat,
        model=args.model,
        max_atoms=args.max_atoms,
        verbose=not args.quiet,
    )
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(enriched, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(stats, indent=2), file=sys.stderr)
    print(f"envelope_backfill: wrote {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
