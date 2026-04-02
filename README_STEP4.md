# Step 4 bundle for `professional_services_text`

This bundle adds the missing curated examples layer and the two compiler modules you called out:

- `machine/professional_services_text_examples.yaml`
- `professional_services_text/compile_retrieval_exemplars.py`
- `professional_services_text/compile_negative_examples.py`
- `professional_services_text/examples_contract_support.py`

## What the YAML includes

- **82 curated retrieval exemplars**
- **70 curated negative examples**
- discourse-profile tags for:
  - `call_transcript`
  - `meeting_notes`
  - `email_thread`
  - `project_memo`
  - `hybrid_notes_memo`
- PurTera-style public service vocabulary and marketing-boilerplate negatives

## Recommended placement in repo

Drop the YAML beside the existing machine YAMLs:

```text
machine/
  professional_services_text_enhanced_machine.yaml
  professional_services_text_rich_all_modalities.yaml
  professional_services_text_examples.yaml
```

Drop the Python modules beside the other pack compilers:

```text
professional_services_text/
  compile_field_table.py
  compile_claim_family_table.py
  compile_review_rule_table.py
  compile_projection_rule_table.py
  compile_allowed_masks.py
  compile_parser_profile_table.py
  compile_retrieval_exemplars.py
  compile_negative_examples.py
  examples_contract_support.py
```

## Recommended compile call

```python
retrieval_table = compile_retrieval_exemplars(
    ir,
    curated_examples_paths=[examples_yaml_path],
    semantic_contract_paths=[
        enhanced_machine_path,
        rich_modalities_path,
        field_catalog_path,
    ],
)

negative_table = compile_negative_examples(
    ir,
    curated_examples_paths=[examples_yaml_path],
    semantic_contract_paths=[
        enhanced_machine_path,
        rich_modalities_path,
        field_catalog_path,
    ],
)
```

## Important integration note

These compilers **do not require** you to patch Canonical IR immediately.
They work off:
- `CanonicalIR`
- curated examples YAML
- optional raw semantic docs for richer harvesting

Longer-term, the cleanest evolution is to add an optional `examples_contract` role to the loader/IR manifest, but this bundle gets you past Step 4 now.
