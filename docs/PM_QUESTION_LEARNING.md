# How PMs teach OrbitBrief questions

OrbitBrief’s **Questions to answer** list is no longer a dump of pack YAML checklists.
It is an evidence-first, project-mode-gated shortlist (top ~5–8) that PMs can teach.

## What you see

For each deal, questions should feel like things a PM would ask themselves before quoting:

- Relevant to the **project mode** (e.g. `network_edge_install` vs `network_ops` vs `alm`)
- Not already answered by sites / BOM / scope evidence
- Ranked by what unblocks the next step

YAML pack checks still run for SOW completeness, but they are only a **rare safety net**
for `customer_questions` — never the primary author.

## Teaching actions (Review queue)

| Action | When to use | Effect |
|--------|-------------|--------|
| **Not needed** | Question is already known / useless | Immediate remove + suppress on future compiles |
| **Wrong project** | Right family, wrong mode (e.g. gold-image on an SD-WAN install) | Immediate remove + demote for this `project_mode` |
| **✎ Note / Resolve** | You answered it for this deal | Settles the card; use **Not needed** if it should never return |
| **+ Suggest question** | The system missed a real ask | Stored as **gold** and promoted on similar modes |

API: `POST /api/quoting/deal/{dealId}/orbitbrief/question-feedback`

```json
{
  "action": "dismiss" | "wrong_for_project" | "edit" | "add" | "answered",
  "ruleId": "mode.network_edge_install.topology_per_site",
  "questionText": "…",
  "editedText": "…",
  "projectMode": "network_edge_install"
}
```

## Where feedback lives

1. `deals/{dealId}/orbitbrief/latest/question_feedback.jsonl` — deal ledger  
2. `orbitbrief/learning/question_feedback.jsonl` — org-wide demote/promote  
3. Immediate patch of `PM_HANDOFF.json` → `customer_questions` (no wait for rebrief)

On the next Core compile/rebrief, the engine loads the JSONL
(`ORBITBRIEF_QUESTION_FEEDBACK_PATH` or `.orbitbrief_question_feedback.jsonl`
beside the case) and applies suppress / gold promote before ranking.

## Project modes (universal)

Detected from envelope evidence + service routing, including:

- `network_edge_install` — SD-WAN / Meraki / remote-hands multi-site turn-up  
- `network_ops` — ongoing maintenance / patch / TAC  
- `wireless_install` / `wireless_config`  
- `cabling_install`, `alm`, `staff_aug`, `av_install`, `access_control`, `generic`

## Engineer notes

- Engine: `orbitbrief_core/pm_handoff/question_engine.py`  
- Feedback store: `orbitbrief_core/pm_handoff/question_feedback.py`  
- Builder wires curated list into `PMHandoff.customer_questions`  
- UI: OrbitBrief v2 Review queue → `useQuestionFeedback`  
