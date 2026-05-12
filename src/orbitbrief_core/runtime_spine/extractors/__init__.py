from .postprocess import postprocess_extractor_output
from .registry import (
    ExtractorRegistry,
    ExtractorRegistryError,
    ExtractorSpec,
    load_extractor_registry,
    resolve_extractor_entrypoint,
)

__all__ = [
    "ExtractorRegistry",
    "ExtractorRegistryError",
    "ExtractorSpec",
    "load_extractor_registry",
    "resolve_extractor_entrypoint",
    "postprocess_extractor_output",
    "ExtractionResult",
    "Extractor",
    "InternalNarrativeClaim",
    "NARRATIVE_CLAIM_FAMILIES",
    "NARRATIVE_CLAIM_ONTOLOGY_VERSION",
    "TEXT_NARRATIVE_EXTRACTOR_PROMPT_VERSION",
    "build_text_narrative_extractor_prompt",
    "intake_only_result",
    "project_to_post_hints",
    "project_to_rich_txt_pre",
    "project_to_slim_pre",
    "NarrativeExtractionResult",
    "InternalClaim",
    "FieldClaim",
    "ExtractionDiagnostic",
    "EvidenceRef",
    "EvidenceRefSet",
    "run_narrative_extractor",
]


def __getattr__(name: str):
    # Legacy extraction helpers are lazily imported because some runtime_spine
    # compatibility modules are intentionally omitted in this workspace.
    if name in {"ExtractionResult", "Extractor"}:
        from .base import ExtractionResult, Extractor

        return {"ExtractionResult": ExtractionResult, "Extractor": Extractor}[name]
    if name == "intake_only_result":
        from .intake_only import intake_only_result

        return intake_only_result
    if name in {"NARRATIVE_CLAIM_FAMILIES", "NARRATIVE_CLAIM_ONTOLOGY_VERSION"}:
        from .narrative_claim_ontology import NARRATIVE_CLAIM_FAMILIES, NARRATIVE_CLAIM_ONTOLOGY_VERSION

        return {
            "NARRATIVE_CLAIM_FAMILIES": NARRATIVE_CLAIM_FAMILIES,
            "NARRATIVE_CLAIM_ONTOLOGY_VERSION": NARRATIVE_CLAIM_ONTOLOGY_VERSION,
        }[name]
    if name in {"NarrativeExtractionResult", "InternalClaim", "FieldClaim", "ExtractionDiagnostic", "EvidenceRef", "EvidenceRefSet"}:
        from .narrative_claim_ontology import (
            EvidenceRef,
            EvidenceRefSet,
            ExtractionDiagnostic,
            FieldClaim,
            InternalClaim,
            NarrativeExtractionResult,
        )

        return {
            "NarrativeExtractionResult": NarrativeExtractionResult,
            "InternalClaim": InternalClaim,
            "FieldClaim": FieldClaim,
            "ExtractionDiagnostic": ExtractionDiagnostic,
            "EvidenceRef": EvidenceRef,
            "EvidenceRefSet": EvidenceRefSet,
        }[name]
    if name in {"InternalNarrativeClaim", "project_to_post_hints", "project_to_rich_txt_pre", "project_to_slim_pre"}:
        from .narrative_projector import InternalNarrativeClaim, project_to_post_hints, project_to_rich_txt_pre, project_to_slim_pre

        return {
            "InternalNarrativeClaim": InternalNarrativeClaim,
            "project_to_post_hints": project_to_post_hints,
            "project_to_rich_txt_pre": project_to_rich_txt_pre,
            "project_to_slim_pre": project_to_slim_pre,
        }[name]
    if name in {"TEXT_NARRATIVE_EXTRACTOR_PROMPT_VERSION", "build_text_narrative_extractor_prompt"}:
        from .narrative_prompt_template import TEXT_NARRATIVE_EXTRACTOR_PROMPT_VERSION, build_text_narrative_extractor_prompt

        return {
            "TEXT_NARRATIVE_EXTRACTOR_PROMPT_VERSION": TEXT_NARRATIVE_EXTRACTOR_PROMPT_VERSION,
            "build_text_narrative_extractor_prompt": build_text_narrative_extractor_prompt,
        }[name]
    if name == "run_narrative_extractor":
        from .narrative_extractor import run_narrative_extractor

        return run_narrative_extractor
    raise AttributeError(name)
