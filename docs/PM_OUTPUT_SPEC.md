# OrbitBrief PM / Solution Architect Output Spec

PMs should not see internal substrate language. They should see a ready-to-use intake QA packet.

## Per-case outputs

```text
PM_EXECUTIVE_SUMMARY.md/html      # short PM landing page
SA_REVIEW_PACKET.md/html          # detailed solution-architect review
PM_HANDOFF.md/html/json           # combined handoff + API payload
```

## Portfolio outputs

```text
PM_PORTFOLIO_DASHBOARD.md/html/json
PM_QUESTION_QUEUE.csv
```

## PM landing-page sections

1. Readiness status: red / yellow / green
2. What the PM does next
3. PM scorecard
4. Confirmed physical sites
5. Detected workstreams
6. Questions to resolve before SOW
7. Customer clarification email starter

## Solution-architect sections

1. SA review lane
2. Source-backed technical/commercial evidence
3. Sites, access, inventory, port/VLAN, BOM, support, risks, validation
4. Source inventory read

## Green/yellow/red

- **Red**: do not publish final SOW; blocker questions remain.
- **Yellow**: draftable with PM review; warning questions remain.
- **Green**: current rulebook found no blockers/warnings.

## UX rule

The PM screen should say "evidence", "workstreams", "confirmed sites", and "questions". Do not show internal words like atom, packet, canonical key, pack_prior, or entity graph.
