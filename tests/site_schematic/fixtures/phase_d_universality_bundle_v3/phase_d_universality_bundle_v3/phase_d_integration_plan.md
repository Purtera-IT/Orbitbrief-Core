# Phase D integration plan (v3)

## Goal
Validate that the parser stack generalizes beyond the current pair by using 10 public holdout packets across the same two packet families:
- telecom / wireless / structured cabling
- low-voltage / security / intercom / hybrid

## What must stay frozen
- canonical production KPI path
- additive topology KPI path
- contradiction lane separation

## Integration order
1. Run `scripts/fetch_public_holdouts.py` (or `.sh`) to populate `pdfs/holdout_public/`.
2. Run `scripts/validate_holdout_presence.py` to confirm which PDFs are present.
3. Hydrate per-packet gold schemas with real page indices / sheet ids / hard-page targets after each PDF is present.
4. Register hydrated packets in the repo's Phase D holdout lane.
5. Run Phase A/B/C/D evaluation packet-by-packet, then registry-wide.
6. Promote only packets with strong semantic fit and stable A/B/C performance into any contradiction-rich lane.

## Success criteria
- 10/10 holdout PDFs downloaded locally
- 10/10 per-packet gold schemas hydrated
- 0 production KPI regressions
- each packet has Phase A/B/C outputs and evidence traces
- contradiction lane remains separate and optional
