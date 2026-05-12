"""Top-level orchestrator: validator report + brain output → calibrated items."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from orbitbrief_core.brains._retrieval_bundle import RetrievalBundle
from orbitbrief_core.brains.managed_services.schema import (
    ManagedServicesScopeState,
)
from orbitbrief_core.calibrator.model import CalibrationModel
from orbitbrief_core.calibrator.signals import SignalVector, extract_signals
from orbitbrief_core.calibrator.verdict import (
    EscalationReason,
    Verdict,
    decide_verdict,
)
from orbitbrief_core.validator.report import ItemRef, ValidationReport
from orbitbrief_core.world_model.planner.schema import BriefState


# Sections we'll calibrate; mirrors the validator's table.
_SECTIONS: tuple[str, ...] = (
    "scope_items",
    "exclusions",
    "customer_responsibilities",
    "milestones",
    "assumptions",
    "dispatch_readiness_flags",
    "open_questions",
)


class CalibratedItem(BaseModel):
    """One brain item, with calibrated confidence + verdict + reasons."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ref: ItemRef
    raw_confidence: float = Field(ge=0.0, le=1.0)
    calibrated_confidence: float = Field(ge=0.0, le=1.0)
    verdict: Verdict
    reasons: tuple[EscalationReason, ...]
    signals: dict[str, float] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)


class CalibratorReport(BaseModel):
    """Per-project calibrator output."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_id: str
    compile_id: str
    brain: str
    items: tuple[CalibratedItem, ...]

    def by_verdict(self) -> dict[str, tuple[CalibratedItem, ...]]:
        out: dict[str, list[CalibratedItem]] = {}
        for it in self.items:
            out.setdefault(it.verdict.value, []).append(it)
        return {k: tuple(v) for k, v in out.items()}


@dataclass
class Calibrator:
    """Stateless calibrator. Wraps the model + verdict decisioning."""

    model: CalibrationModel = field(default_factory=CalibrationModel)
    auto_accept_threshold: float = 0.80
    review_threshold: float = 0.55

    def calibrate_managed_services(
        self,
        state: ManagedServicesScopeState,
        *,
        validation: ValidationReport,
        brief: BriefState,
        bundle: RetrievalBundle,
        parser_confidence_by_atom: dict[str, float] | None = None,
    ) -> CalibratorReport:
        """Calibrate every grounded item in a :class:`ManagedServicesScopeState`."""
        # Pre-index validations by composite item id for O(1) lookup.
        val_by_id = {iv.item.composite_id: iv for iv in validation.items}

        out: list[CalibratedItem] = []
        for section in _SECTIONS:
            for item in getattr(state, section):
                ref = ItemRef(
                    project_id=state.project_id,
                    compile_id=state.compile_id,
                    brain="managed_services",
                    section=section,
                    item_id=item.id,
                )
                item_validation = val_by_id.get(ref.composite_id)
                sig = extract_signals(
                    item=item,
                    section=section,
                    state=state,
                    bundle=bundle,
                    brief=brief,
                    item_validation=item_validation,
                    parser_confidence_by_atom=parser_confidence_by_atom,
                )
                raw = self.model.raw_score(sig)
                calibrated = self.model.calibrated(sig)
                verdict, reasons = decide_verdict(
                    calibrated_prob=calibrated,
                    item_validation=item_validation,
                    auto_accept_threshold=self.auto_accept_threshold,
                    review_threshold=self.review_threshold,
                )
                out.append(
                    CalibratedItem(
                        ref=ref,
                        raw_confidence=raw,
                        calibrated_confidence=calibrated,
                        verdict=verdict,
                        reasons=reasons,
                        signals=sig.as_features(),
                        payload=item.model_dump(mode="json"),
                    )
                )
        return CalibratorReport(
            project_id=state.project_id,
            compile_id=state.compile_id,
            brain="managed_services",
            items=tuple(out),
        )
