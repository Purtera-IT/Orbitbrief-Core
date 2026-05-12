This kit contains:

1. universal_table_contract_spec.md
   - Human-readable architecture + hard pages + perfect gold criteria.

2. universal_table_contract_schema.json
   - Machine-readable universal parser-level table contract.

3. universal_table_gold_standard.json
   - Hard-page manifest and strict perfect acceptance rules.

4. cursor_prompt_universal_table_spine.txt
   - Detailed Cursor prompt for integrating the contract into the current stack.

Intended use:
- Feed the prompt + files to Cursor
- Implement Phase 1 parser-only lossless table spine
- Evaluate against the hard pages chosen from the two benchmark PDFs
- Keep OrbitBrief downstream and untouched