from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

from orbitbrief_core.parser.router import ParsePlan, RouterInput
from orbitbrief_core.parser.shared.types import DocumentParse


@dataclass(frozen=True, slots=True)
class AdapterInfo:
    """Human-readable metadata about an adapter implementation."""

    name: str
    modality: str
    description: str
    optional_dependencies: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


class BaseAdapter(Protocol):
    """Shared contract for all container frontends."""

    info: AdapterInfo

    def parse(
        self,
        *,
        router_input: RouterInput,
        parse_plan: ParsePlan,
        compiled_pack: Any,
    ) -> DocumentParse:
        ...


class AbstractAdapter(ABC):
    """Base class for concrete adapter implementations."""

    info: AdapterInfo

    @abstractmethod
    def parse(
        self,
        *,
        router_input: RouterInput,
        parse_plan: ParsePlan,
        compiled_pack: Any,
    ) -> DocumentParse:
        raise NotImplementedError
