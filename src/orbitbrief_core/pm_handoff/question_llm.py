"""Deal-specific exposure questions, written by a model, grounded in atoms.

Templates cannot ask what nobody wrote down in advance. That is not a gap in the
templates; it is what a fixed list IS. Reviewed against two real briefs
2026-08-13, the template output was strong on technical execution and blind to
commercial and logistics exposure — the questions whose absence from a SOW costs
money rather than time:

* Clayton, 437-store T&M dispatch: nothing asked who eats an aborted visit when
  a tech arrives and the store is shut, nothing asked about travel / per diem on
  a national footprint, nothing asked whether billing is the rate card's $/hour
  or its $/day.
* NYC display install: the brief asked whether a live DATA drop exists at each
  mount and never asked about POWER; it never asked for the building's
  certificate of insurance or a booked freight elevator, which is the single
  most common reason a Manhattan install does not happen on the day.

None of those are template families. All of them are obvious to a PM reading the
deal. So ask a model to read the deal.

The contract is the same one every other generator obeys: no question without
evidence. The model must cite atom ids; citations are verified against real ids
and a question that cites nothing is dropped, not softened. It cannot invent a
site, a price, or a commitment and have it survive.

Off unless a client is wired, and additive when on — these candidates join the
same pool and the same MMR ranker as everything else, so a bad batch is
out-ranked rather than published.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Iterable, Mapping, Protocol, Sequence

log = logging.getLogger(__name__)

_MAX_ATOMS = 60
_MAX_ATOM_CHARS = 320
_MAX_QUESTIONS = 8


class ChatLike(Protocol):
    def complete(self, messages: list[Any], *, model: str, **kwargs: Any) -> str: ...


_SYSTEM = """You are a senior Project Manager reviewing a services deal BEFORE the
SOW is signed. You have already been given the questions the system asks by rule.

Your job is the residue: the exposure nobody asked about, that is specific to
THIS deal, and that costs real money if it is not written into the SOW.

What qualifies:
* Commercial exposure — billing unit, travel and per diem, minimum callout,
  aborted or wasted visits, change-order triggers, who absorbs a repeat trip.
* Logistics that gate the work happening at all — building COI, freight
  elevator, dock booking, delivery and storage of customer-furnished kit,
  disposal of packaging or removed gear, badge lead time.
* Preconditions — what must be true before a crew mobilizes, and who confirms it.
* Scale consequences — a policy that is trivial at one site and ruinous at 400.

What does NOT qualify:
* Anything already covered by the questions you were given.
* Generic project hygiene that would read the same on any deal ("confirm the
  schedule", "confirm the scope"). If it could be asked of a deal you have not
  read, it is wrong.
* Anything you cannot point at evidence for.

Every question MUST cite at least one evidence tag from the EVIDENCE block —
the bracketed tag at the start of each line, like E1 or E17. Cite the tag whose
line makes the question necessary: the rate card line, the exclusion, the site
count, the delivery note. If you cannot cite one, do not ask the question.

Reply with ONLY a JSON array, no prose:
[
  {"question": "...", "label": "3-6 words", "why": "what it costs if omitted",
   "severity": "blocker" | "warning", "atom_ids": ["E1", "E7"]}
]
At most %d questions. Fewer, sharper questions beat a long list.""" % _MAX_QUESTIONS


def _atom_id(a: Mapping[str, Any]) -> str:
    return str(a.get("id") or a.get("atom_id") or "").strip()


def _pick_atoms(atoms: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Prefer commercial / logistics / constraint atoms — the exposure lives there.

    A stride sample over 1900 atoms mostly returns scope prose, which is what the
    rule-based generators already read. The questions that are missing come from
    rate cards, exclusions, delivery notes and site rosters.
    """
    priority = (
        "commercial_total", "pricing_assumption", "rate_card", "bom_line",
        "vendor_line_item", "exclusion", "constraint", "customer_instruction",
        "assumption", "change_order_rule", "lead_time_constraint",
        "acceptance_criterion", "responsibility", "milestone_phase",
    )
    # Cap per type. Taking priority types in order let pricing_assumption (218
    # of them on Clayton) and commercial_total fill all 60 slots between them,
    # so the model saw a rate card and no exclusions, no constraints and no
    # scope — it cannot spot a missing COI in a wall of unit prices. Breadth
    # across families is the point; depth within one is not.
    per_type = max(3, _MAX_ATOMS // max(1, len(priority)))
    ranked: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for want in priority:
        taken = 0
        for a in atoms:
            if len(ranked) >= _MAX_ATOMS or taken >= per_type:
                break
            aid = _atom_id(a)
            if not aid or aid in seen:
                continue
            if str(a.get("atom_type") or "") == want:
                seen.add(aid)
                ranked.append(a)
                taken += 1
    # Top up with scope prose so the model knows what the work actually is.
    for a in atoms:
        if len(ranked) >= _MAX_ATOMS:
            break
        aid = _atom_id(a)
        if aid and aid not in seen:
            seen.add(aid)
            ranked.append(a)
    return ranked


def _parse(reply: str) -> list[dict[str, Any]]:
    text = (reply or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        rows = json.loads(text[start : end + 1])
    except Exception:
        return []
    return [r for r in rows if isinstance(r, dict)]


def candidates_from_llm(
    *,
    atoms: Iterable[Mapping[str, Any]],
    project_mode: str,
    existing_questions: Sequence[str],
    chat: ChatLike | None,
    model: str,
    deal_label: str = "",
    diagnostics: dict[str, Any] | None = None,
) -> list[Any]:
    """Deal-specific exposure questions. Empty list on any failure."""
    if chat is None or not model:
        return []
    atom_list = [a for a in atoms if isinstance(a, Mapping) and _atom_id(a)]
    if not atom_list:
        return []
    from orbitbrief_core.pm_handoff.question_engine import QuestionCandidate

    picked = _pick_atoms(atom_list)
    # Cite E1/E2/E3, not the raw atom id. The ids are long opaque strings, and
    # asking a model to copy one back exactly is a needless failure mode: the
    # first live run returned zero usable questions with every one dropped at
    # the citation check. A short tag it can echo, mapped back here, keeps the
    # grounding contract identical while removing the transcription burden.
    token_to_id = {f"E{i + 1}": _atom_id(a) for i, a in enumerate(picked)}
    id_set = {v for v in token_to_id.values() if v}
    evidence = "\n".join(
        f"[E{i + 1}] ({a.get('atom_type')}) {str(a.get('text') or '')[:_MAX_ATOM_CHARS]}"
        for i, a in enumerate(picked)
    )
    already = "\n".join(f"- {q}" for q in existing_questions[:20] if q)
    user = (
        f"DEAL: {deal_label or '(unnamed)'}\nWORK TYPE: {project_mode or 'unclassified'}\n\n"
        f"QUESTIONS ALREADY BEING ASKED:\n{already or '(none)'}\n\n"
        f"EVIDENCE (atom_id, type, text):\n{evidence}\n\n"
        "Now list the exposure nobody asked about."
    )
    try:
        from orbitbrief_core.inference.client import ChatMessage

        messages: list[Any] = [ChatMessage("system", _SYSTEM), ChatMessage("user", user)]
    except Exception:  # pragma: no cover - stub clients in tests
        messages = [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": user},
        ]
    if diagnostics is not None:
        # Is the run-to-run variance ours or the model's?
        #
        # The same deal produced 8, 8, 8 then 0 candidates, and different
        # questions each time. temperature is already 0 (OpenAIChatClient
        # defaults it and sends it), so either the INPUT differs between runs or
        # the hosted model is simply not deterministic at temperature 0 -- which
        # is true of DeepSeek and most hosted MoE serving. Those need opposite
        # fixes, so hash what we actually sent: identical input_sha across runs
        # with differing output proves the model; differing input_sha proves us.
        import hashlib as _h

        diagnostics["input_sha"] = _h.sha256(user.encode("utf-8")).hexdigest()[:16]
        diagnostics["atom_ids_sha"] = _h.sha256(
            "|".join(_atom_id(a) for a in picked).encode("utf-8")
        ).hexdigest()[:16]
    try:
        reply = chat.complete(messages, model=model, max_tokens=1400)
    except Exception as exc:  # a dead endpoint must never fail a compile
        log.warning("question_llm: model call failed (%s); no candidates", exc)
        if diagnostics is not None:
            diagnostics["error"] = f"{type(exc).__name__}: {exc}"[:200]
        return []

    rows = _parse(reply if isinstance(reply, str) else str(reply))
    out: list[Any] = []
    dropped_uncited = 0
    for i, row in enumerate((rows)):
        q = str(row.get("question") or "").strip()
        if len(q) < 20:
            continue
        raw_cites = [str(x).strip() for x in (row.get("atom_ids") or []) if str(x).strip()]
        cited: list[str] = []
        for c in raw_cites:
            # Accept the token we asked for, or a real id if it echoed one.
            resolved = token_to_id.get(c.upper()) or (c if c in id_set else "")
            if resolved and resolved not in cited:
                cited.append(resolved)
        if not cited:
            # The whole contract. An uncited question is a guess with a
            # confident voice, and this generator has no rule behind it to fall
            # back on — so it is dropped, never softened.
            dropped_uncited += 1
            continue
        label = str(row.get("label") or "").strip() or "Deal exposure"
        why = str(row.get("why") or "").strip()
        sev = "blocker" if str(row.get("severity") or "").lower() == "blocker" else "warning"
        out.append(
            QuestionCandidate(
                rule_id=f"llm.exposure.{re.sub(r'[^a-z0-9]+', '_', label.lower())[:40] or i}",
                domain_id="commercial",
                label=label[:60],
                severity=sev,
                message=why[:240] or f"Deal-specific exposure: {label}",
                suggested_open_question=q[:400],
                observed_summary=(why or q)[:240],
                source="llm_exposure",
                score=0.87 if sev == "blocker" else 0.83,
                evidence_atom_ids=cited[:4],
                project_mode=project_mode,
            )
        )
    if diagnostics is not None:
        # On a zero-yield run this is the only way to see WHY without shipping
        # the whole reply into the artifact: how much came back, how much parsed,
        # how much failed the citation check, and a short sample when nothing
        # survived. Guessing cost a full deploy cycle the first time.
        diagnostics["reply_chars"] = len(reply) if isinstance(reply, str) else 0
        diagnostics["parsed_rows"] = len(rows)
        diagnostics["dropped_uncited"] = dropped_uncited
        diagnostics["atoms_offered"] = len(picked)
        if not out:
            diagnostics["sample_reply"] = str(reply)[:400]
    if dropped_uncited:
        log.info("question_llm: dropped %d uncited question(s)", dropped_uncited)
    log.info("question_llm: %d exposure question(s) from %d atoms", len(out), len(picked))
    return out


__all__ = ["candidates_from_llm"]
