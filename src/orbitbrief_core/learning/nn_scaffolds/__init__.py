"""Six scaffolded NN mechanisms — all DISCONNECTED.

See ``README.md`` in this directory for the full table of mechanisms,
activation gates, and the rationale for why six small models beat one
big LoRA fine-tune for this product shape.

Importing this package or any submodule does nothing at runtime. Each
module exports its own ``IS_ACTIVE = False`` sentinel that downstream
code checks before routing through the NN.
"""
from __future__ import annotations

# Each submodule defines its own IS_ACTIVE sentinel.
# Re-export the names so callers can do:
#   from orbitbrief_core.learning.nn_scaffolds import IS_ANY_ACTIVE
from orbitbrief_core.learning.nn_scaffolds.atom_type_classifier import (
    IS_ACTIVE as ATOM_TYPE_CLASSIFIER_ACTIVE,
)
from orbitbrief_core.learning.nn_scaffolds.embedding_head_finetune import (
    IS_ACTIVE as EMBEDDING_HEAD_FINETUNE_ACTIVE,
)
from orbitbrief_core.learning.nn_scaffolds.entity_cross_encoder import (
    IS_ACTIVE as ENTITY_CROSS_ENCODER_ACTIVE,
)
from orbitbrief_core.learning.nn_scaffolds.gap_rule_generator import (
    IS_ACTIVE as GAP_RULE_GENERATOR_ACTIVE,
)
from orbitbrief_core.learning.nn_scaffolds.margin_regression import (
    IS_ACTIVE as MARGIN_REGRESSION_ACTIVE,
)
from orbitbrief_core.learning.nn_scaffolds.pm_rejection_classifier import (
    IS_ACTIVE as PM_REJECTION_CLASSIFIER_ACTIVE,
)

IS_ANY_ACTIVE: bool = any(
    [
        ATOM_TYPE_CLASSIFIER_ACTIVE,
        EMBEDDING_HEAD_FINETUNE_ACTIVE,
        ENTITY_CROSS_ENCODER_ACTIVE,
        GAP_RULE_GENERATOR_ACTIVE,
        MARGIN_REGRESSION_ACTIVE,
        PM_REJECTION_CLASSIFIER_ACTIVE,
    ]
)

__all__ = [
    "ATOM_TYPE_CLASSIFIER_ACTIVE",
    "EMBEDDING_HEAD_FINETUNE_ACTIVE",
    "ENTITY_CROSS_ENCODER_ACTIVE",
    "GAP_RULE_GENERATOR_ACTIVE",
    "MARGIN_REGRESSION_ACTIVE",
    "PM_REJECTION_CLASSIFIER_ACTIVE",
    "IS_ANY_ACTIVE",
]
