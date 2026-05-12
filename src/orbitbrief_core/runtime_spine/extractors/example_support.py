from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


def _tail_id(value: str) -> str:
    text = str(value or "").strip()
    if ":" in text:
        return text.rsplit(":", 1)[-1]
    return text


def _tokenize(value: str) -> set[str]:
    return {token.strip(".,:;!?()[]{}\"'").lower() for token in value.split() if token.strip()}


@dataclass(frozen=True, slots=True)
class ExemplarSupportRow:
    exemplar_id: str
    text: str
    claim_families: tuple[str, ...]
    modalities: tuple[str, ...]
    discourse_profiles: tuple[str, ...]
    weight: float


@dataclass(frozen=True, slots=True)
class NegativeSupportRow:
    negative_example_id: str
    text: str
    claim_families: tuple[str, ...]
    modalities: tuple[str, ...]
    discourse_profiles: tuple[str, ...]
    severity: str


@dataclass(frozen=True, slots=True)
class ExampleSupportAssets:
    exemplars: tuple[ExemplarSupportRow, ...]
    negatives: tuple[NegativeSupportRow, ...]

    @classmethod
    def from_rows(
        cls,
        *,
        retrieval_exemplars: tuple[Mapping[str, object], ...],
        negative_examples: tuple[Mapping[str, object], ...],
    ) -> "ExampleSupportAssets":
        exemplars: list[ExemplarSupportRow] = []
        for row in retrieval_exemplars:
            linked = row.get("linked_claim_family_ids", ())
            families = tuple(sorted(_tail_id(str(item)) for item in linked if _tail_id(str(item))))
            modalities = tuple(sorted(str(item) for item in row.get("modalities", ()) if str(item)))
            discourse = tuple(sorted(str(item) for item in row.get("discourse_profiles", ()) if str(item)))
            text = str(row.get("text", "")).strip()
            if not text:
                continue
            exemplars.append(
                ExemplarSupportRow(
                    exemplar_id=str(row.get("exemplar_id", "")).strip(),
                    text=text,
                    claim_families=families,
                    modalities=modalities,
                    discourse_profiles=discourse,
                    weight=float(row.get("weight", 1.0) or 1.0),
                )
            )
        negatives: list[NegativeSupportRow] = []
        for row in negative_examples:
            linked = row.get("linked_claim_family_ids", ())
            families = tuple(sorted(_tail_id(str(item)) for item in linked if _tail_id(str(item))))
            modalities = tuple(sorted(str(item) for item in row.get("modalities", ()) if str(item)))
            discourse = tuple(sorted(str(item) for item in row.get("discourse_profiles", ()) if str(item)))
            text = str(row.get("text", "")).strip()
            if not text:
                continue
            negatives.append(
                NegativeSupportRow(
                    negative_example_id=str(row.get("negative_example_id", "")).strip(),
                    text=text,
                    claim_families=families,
                    modalities=modalities,
                    discourse_profiles=discourse,
                    severity=str(row.get("severity", "medium")).strip() or "medium",
                )
            )
        return cls(exemplars=tuple(exemplars), negatives=tuple(negatives))

    def exemplar_count_for_claim_family(self, claim_family: str, *, modality: str) -> int:
        return sum(
            1
            for item in self.exemplars
            if claim_family in item.claim_families and (not item.modalities or modality in item.modalities)
        )

    def negative_overlap(self, text: str, *, claim_family: str, modality: str) -> tuple[str, ...]:
        text_tokens = _tokenize(text)
        if not text_tokens:
            return ()
        hits: list[str] = []
        for item in self.negatives:
            if item.claim_families and claim_family not in item.claim_families:
                continue
            if item.modalities and modality not in item.modalities:
                continue
            overlap = len(text_tokens & _tokenize(item.text)) / max(1, len(_tokenize(item.text)))
            if overlap >= 0.8:
                hits.append(item.negative_example_id)
        return tuple(sorted(set(hits)))
