"""Phase 100 — institutional memory.

Captures every closed deal as a learning record + retrieves similar
past deals + mines patterns + retrains the calibrator. Set up now so
the system learns automatically as soon as deals close — no manual
re-wiring needed when the corpus reaches scale.

Four sub-modules with progressive activation thresholds:

* ``learning_ledger`` — extended schema for closed deals. Backwards
  compatible with the existing :func:`pm_intelligence.write_corpus_history`
  ledger; readers fall through gracefully on missing fields.

* ``retrieve_similar_deals`` — top-K nearest past deals by domain
  overlap + deal value. Useful from ~20 closed deals onward.

* ``pattern_miner`` — frequency tables ("87% of copper_cabling deals
  included a basement IDF cabinet"), margin correlations ("deals
  with PoE undersizing lost 4 pp of margin on average"). Useful from
  ~50 deals per domain.

* ``lora_scaffold`` — empty placeholder for fine-tuned LoRA. Not
  connected to the live pipeline. Activate manually at 500+ deals
  per domain (or skip — most products never get here).
"""
from orbitbrief_core.learning.learning_ledger import (
    LearningLedger,
    LearningRecord,
    PmDecisionRecord,
)
from orbitbrief_core.learning.pattern_miner import (
    DomainPatterns,
    MarginCorrelation,
    mine_patterns,
)
from orbitbrief_core.learning.retrieve_similar_deals import (
    RetrievalHit,
    retrieve_similar_deals,
)

__all__ = [
    "LearningLedger",
    "LearningRecord",
    "PmDecisionRecord",
    "DomainPatterns",
    "MarginCorrelation",
    "RetrievalHit",
    "mine_patterns",
    "retrieve_similar_deals",
]
