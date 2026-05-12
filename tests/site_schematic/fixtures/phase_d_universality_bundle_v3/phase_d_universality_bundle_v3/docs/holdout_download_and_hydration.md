# Holdout packet download + hydration workflow

1. Run the downloader:
   - `python scripts/fetch_public_holdouts.py`
   - or `bash scripts/fetch_public_holdouts.sh`
2. Validate presence:
   - `python scripts/validate_holdout_presence.py > compiled_artifacts/phase_d_holdout_presence.json`
3. For each present packet, hydrate its gold schema with:
   - real page indices
   - real hard pages
   - real sheet ids/titles
4. Register hydrated packets into the repo's Phase D holdout lane.
5. Run the full Phase A-D suite.

If any download fails, keep the packet in `awaiting_download` and do not claim universality for that packet yet.
