"""v46 — Risk Propagation Net.

Three layers, no trained weights at boot:

* :mod:`passthrough` — surface the eight envelope-curated views that
  parser-os already computes but the historical handoff builder drops.

* :mod:`scorers` — graph-feature risk scoring (atom_risk,
  site_cost_overrun, milestone_slip, stakeholder_bottleneck).  Output
  is calibrated probabilities derived from authority_rank, edge
  density, contradiction density, source-replay verification.

* :mod:`consensus` — Cross-Authority Consensus Net.  For each
  PM-visible claim, score it by the diversity + rank of supporting
  atoms across authority classes.  A claim backed by SOW +
  vendor_quote + transcript is much stronger than three emails.

All three can be invoked from ``compile_brief`` after the pipeline
runs and before polish.  None require trained model weights.
"""
from orbitbrief_core.risk_net.passthrough import apply_envelope_passthroughs
from orbitbrief_core.risk_net.scorers import apply_risk_signals
from orbitbrief_core.risk_net.consensus import apply_claim_consensus
from orbitbrief_core.risk_net.narrator import apply_section_narration

__all__ = [
    "apply_envelope_passthroughs",
    "apply_risk_signals",
    "apply_claim_consensus",
    "apply_section_narration",
]
