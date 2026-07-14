"""PM question feedback store — dismiss / wrong / edit / add learning loop.

Append-only JSONL. Used by the customer-question engine to immediately
suppress demoted families and promote PM-authored gold questions on
future deals with the same project mode.

Env:
  ORBITBRIEF_QUESTION_FEEDBACK_PATH — override path to the JSONL ledger
  (default: ``<artifacts>/.orbitbrief_question_feedback.jsonl`` or cwd).
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

# Actions the PM can take (product surface).
ACTION_DISMISS = "dismiss"  # not needed / already known
ACTION_WRONG_FOR_PROJECT = "wrong_for_project"
ACTION_EDIT = "edit"
ACTION_ADD = "add"  # "this would be a question"
ACTION_ANSWERED = "answered"

# Map Platform-infra orbitbrief_run_feedback.decision → engine action.
DECISION_TO_ACTION = {
    "false_positive": ACTION_DISMISS,
    "already_in_source": ACTION_DISMISS,
    "ignore_for_project": ACTION_WRONG_FOR_PROJECT,
    "mark_answered": ACTION_ANSWERED,
    "add_new_rule": ACTION_ADD,
    "ask_customer": ACTION_ANSWERED,  # kept = useful; soft positive
    # Explicit product verbs (new API path)
    "dismiss": ACTION_DISMISS,
    "not_needed": ACTION_DISMISS,
    "wrong_for_project": ACTION_WRONG_FOR_PROJECT,
    "edit": ACTION_EDIT,
    "add": ACTION_ADD,
    "answered": ACTION_ANSWERED,
}

_NEGATIVE_ACTIONS = frozenset({ACTION_DISMISS, ACTION_WRONG_FOR_PROJECT})
_POSITIVE_ACTIONS = frozenset({ACTION_ADD, ACTION_EDIT, ACTION_ANSWERED})


@dataclass(frozen=True)
class QuestionFeedbackEvent:
    """One PM teaching event for the question engine."""

    deal_id: str
    action: str
    project_mode: str = ""
    rule_id: str = ""
    fingerprint: str = ""
    question_text: str = ""
    edited_text: str = ""
    domain_id: str = ""
    actor: str = ""
    compile_id: str = ""
    evidence_atom_ids: list[str] = field(default_factory=list)
    created_at: str = ""

    def to_jsonable(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_jsonable(cls, row: MappingLike) -> "QuestionFeedbackEvent | None":
        if not isinstance(row, dict):
            return None
        action = str(row.get("action") or "").strip()
        if not action:
            decision = str(row.get("decision") or "").strip()
            action = DECISION_TO_ACTION.get(decision, "")
        if not action:
            return None
        return cls(
            deal_id=str(row.get("deal_id") or row.get("case_id") or ""),
            action=action,
            project_mode=str(row.get("project_mode") or ""),
            rule_id=str(row.get("rule_id") or ""),
            fingerprint=str(row.get("fingerprint") or ""),
            question_text=str(
                row.get("question_text")
                or row.get("comment")
                or row.get("question")
                or ""
            ),
            edited_text=str(row.get("edited_text") or row.get("final_text") or ""),
            domain_id=str(row.get("domain_id") or ""),
            actor=str(row.get("actor") or row.get("user_email") or row.get("reviewer") or ""),
            compile_id=str(row.get("compile_id") or ""),
            evidence_atom_ids=[
                str(x) for x in (row.get("evidence_atom_ids") or []) if str(x).strip()
            ],
            created_at=str(row.get("created_at") or ""),
        )


# typing alias without importing Mapping for runtime
MappingLike = Any


def default_feedback_path(case_dir: Path | None = None) -> Path:
    env = os.environ.get("ORBITBRIEF_QUESTION_FEEDBACK_PATH", "").strip()
    if env:
        return Path(env).expanduser()
    if case_dir is not None:
        return Path(case_dir) / ".orbitbrief_question_feedback.jsonl"
    return Path.cwd() / ".orbitbrief_question_feedback.jsonl"


def fingerprint_question(text: str) -> str:
    """Stable fingerprint for a question string (mode-agnostic)."""
    norm = re.sub(r"\s+", " ", (text or "").strip().lower())
    norm = re.sub(r"[^\w\s\?/]", "", norm)
    return norm[:240]


def append_feedback(
    event: QuestionFeedbackEvent,
    *,
    path: Path | None = None,
    case_dir: Path | None = None,
) -> Path:
    """Append one event. Creates parent dirs as needed."""
    target = path or default_feedback_path(case_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    row = event.to_jsonable()
    if not row.get("created_at"):
        row["created_at"] = datetime.now(timezone.utc).isoformat()
    if not row.get("fingerprint") and row.get("question_text"):
        row["fingerprint"] = fingerprint_question(str(row["question_text"]))
    with target.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return target


def load_feedback(
    *,
    path: Path | None = None,
    case_dir: Path | None = None,
    extra_paths: Iterable[Path] = (),
) -> list[QuestionFeedbackEvent]:
    """Load all feedback events from the primary ledger + optional extras."""
    paths: list[Path] = []
    primary = path or default_feedback_path(case_dir)
    paths.append(primary)
    for p in extra_paths:
        if p and p not in paths:
            paths.append(Path(p))
    out: list[QuestionFeedbackEvent] = []
    for p in paths:
        if not p.exists():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            ev = QuestionFeedbackEvent.from_jsonable(row)
            if ev is not None:
                out.append(ev)
    return out


@dataclass(frozen=True)
class FeedbackPolicy:
    """Compiled demote / promote rules from the feedback ledger."""

    suppressed_rule_ids: frozenset[str] = frozenset()
    suppressed_fingerprints: frozenset[str] = frozenset()
    # (project_mode, rule_id) pairs demoted for wrong_for_project
    suppressed_mode_rules: frozenset[tuple[str, str]] = frozenset()
    # Raw texts of dismissed asks — used for semantic neighbor suppress.
    suppressed_texts: tuple[str, ...] = ()
    # Gold questions authored by PMs, keyed by project_mode ("" = global)
    gold_by_mode: dict[str, tuple[QuestionFeedbackEvent, ...]] = field(default_factory=dict)
    # Edited wording preferences: rule_id → preferred text
    edits_by_rule: dict[str, str] = field(default_factory=dict)


def compile_feedback_policy(
    events: Iterable[QuestionFeedbackEvent],
    *,
    dismiss_threshold: int = 1,
) -> FeedbackPolicy:
    """Turn raw events into immediate suppress / promote policy.

    Threshold defaults to 1 so a single PM dismiss takes effect on the
    next compile (product: teach the system immediately). Aggregate
    counts still matter for mode-scoped wrong_for_project demotions.
    """
    dismiss_counts: dict[str, int] = {}
    fp_dismiss: dict[str, int] = {}
    mode_rule_wrong: dict[tuple[str, str], int] = {}
    gold: dict[str, list[QuestionFeedbackEvent]] = {}
    edits: dict[str, str] = {}
    suppressed_text_list: list[str] = []

    for ev in events:
        action = ev.action
        rid = (ev.rule_id or "").strip()
        fp = (ev.fingerprint or fingerprint_question(ev.question_text)).strip()
        mode = (ev.project_mode or "").strip()

        if action in _NEGATIVE_ACTIONS:
            if rid:
                dismiss_counts[rid] = dismiss_counts.get(rid, 0) + 1
                if action == ACTION_WRONG_FOR_PROJECT and mode:
                    mode_rule_wrong[(mode, rid)] = mode_rule_wrong.get((mode, rid), 0) + 1
            if fp:
                fp_dismiss[fp] = fp_dismiss.get(fp, 0) + 1
            text = (ev.question_text or ev.edited_text or "").strip()
            if text:
                suppressed_text_list.append(text)
        elif action == ACTION_EDIT:
            text = (ev.edited_text or ev.question_text or "").strip()
            if rid and text:
                edits[rid] = text
        elif action == ACTION_ADD:
            text = (ev.edited_text or ev.question_text or "").strip()
            if not text:
                continue
            gold.setdefault(mode, []).append(ev)

    suppressed_rules = frozenset(
        rid for rid, n in dismiss_counts.items() if n >= dismiss_threshold
    )
    suppressed_fps = frozenset(
        fp for fp, n in fp_dismiss.items() if n >= dismiss_threshold
    )
    suppressed_mode = frozenset(
        key for key, n in mode_rule_wrong.items() if n >= dismiss_threshold
    )
    gold_by_mode = {m: tuple(evs) for m, evs in gold.items()}
    # De-dupe suppressed texts while preserving order.
    seen_t: set[str] = set()
    uniq_texts: list[str] = []
    for t in suppressed_text_list:
        key = fingerprint_question(t)
        if key in seen_t:
            continue
        seen_t.add(key)
        uniq_texts.append(t)
    return FeedbackPolicy(
        suppressed_rule_ids=suppressed_rules,
        suppressed_fingerprints=suppressed_fps,
        suppressed_mode_rules=suppressed_mode,
        suppressed_texts=tuple(uniq_texts),
        gold_by_mode=gold_by_mode,
        edits_by_rule=edits,
    )
