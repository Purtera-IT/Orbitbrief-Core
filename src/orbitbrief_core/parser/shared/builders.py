from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from datetime import datetime
from typing import Any, Mapping, Sequence

from orbitbrief_core.parser.shared.types import (
    AuthorityClass,
    BBox,
    CharRange,
    ChronologyEdge,
    ChronologyGraph,
    ContainerType,
    DiscourseType,
    EvidenceEdge,
    EvidenceGraph,
    EvidenceKind,
    EvidenceSpan,
    PacketCandidate,
    PacketKind,
    PageRef,
    RelationType,
    ReviewCategory,
    ReviewFlag,
    ReviewSeverity,
    SectionNode,
    SectionTree,
    SourceLayer,
    ThreadEdge,
    ThreadGraph,
    TimeAnchor,
    ActorEdge,
    ActorGraph,
    ActorNode,
    DocumentParse,
    MessageNode,
)


class BuilderError(ValueError):
    """Base builder failure."""


class DuplicateIdError(BuilderError):
    """Raised when an object ID is reused."""


class MissingReferenceError(BuilderError):
    """Raised when a referenced object ID is missing."""


class ValidationError(BuilderError):
    """Raised for invalid local input shape."""


class GraphIntegrityError(BuilderError):
    """Raised when assembled graphs are inconsistent."""


class _IdFactory:
    """Deterministic, per-kind ID generator scoped by doc_id."""

    def __init__(self, doc_id: str) -> None:
        self._doc_id = doc_id
        self._counts: dict[str, int] = {}

    def next(self, kind: str) -> str:
        current = self._counts.get(kind, 0) + 1
        self._counts[kind] = current
        return f"{kind}:{self._doc_id}:{current:06d}"


def _freeze_tuple(values: Sequence[str] | None) -> tuple[str, ...]:
    if values is None:
        return ()
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        out.append(text)
        seen.add(text)
    return tuple(out)


def _normalize_section_path(value: str | Sequence[str] | None) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        parts = [part.strip() for part in value.split("/") if part.strip()]
        return tuple(parts)
    return _freeze_tuple([str(v) for v in value])


def _validate_score(name: str, value: float) -> None:
    if value < 0.0 or value > 1.0:
        raise ValidationError(f"{name} must be in [0.0, 1.0]")


def _validate_char_range(value: CharRange | tuple[int, int] | None) -> CharRange | None:
    if value is None:
        return None
    if isinstance(value, CharRange):
        return value
    start, end = value
    return CharRange(start=start, end=end)


def _validate_bbox(value: BBox | tuple[float, float, float, float] | None, *, page_index: int | None = None) -> BBox | None:
    if value is None:
        return None
    if isinstance(value, BBox):
        return value
    x0, y0, x1, y1 = value
    return BBox(x0=x0, y0=y0, x1=x1, y1=y1, page_index=page_index)


def _validate_relation_type(value: RelationType | str) -> RelationType:
    if isinstance(value, RelationType):
        return value
    try:
        return RelationType(str(value))
    except Exception as exc:  # pragma: no cover - defensive path
        raise ValidationError(f"Unknown relation type: {value}") from exc


def _normalize_email(value: str | None) -> str | None:
    if value is None:
        return None
    email = value.strip().lower()
    if not email:
        return None
    if "@" not in email:
        raise ValidationError("Actor email must include '@'")
    return email


def _require_prefix(object_id: str, expected_prefix: str) -> None:
    if not object_id.startswith(f"{expected_prefix}:"):
        raise ValidationError(f"ID '{object_id}' must start with '{expected_prefix}:'")


class DocumentParseBuilder:
    """Canonical builder for parser IR construction and integrity checks."""

    # Cross-reference classes that are allowed to be unresolved at add-time.
    _DEFERRED_REF_KINDS: frozenset[str] = frozenset(
        {
            "section.parent",
            "message.parent",
            "message.section",
            "message.time_anchor",
            "message.span",
            "span.message",
            "span.time_anchor",
            "span.previous",
            "span.next",
            "span.review_flag",
            "flag.span",
            "edge.thread",
            "edge.chronology",
            "edge.evidence",
            "edge.actor_span",
            "packet.span",
            "packet.actor",
            "packet.message",
            "packet.time_anchor",
            "attach.section_span",
            "attach.message_span",
            "attach.actor_span",
        }
    )

    def __init__(
        self,
        *,
        doc_id: str,
        pack_id: str,
        role_id: str,
        modality: str,
        container_type: ContainerType,
        discourse_type: DiscourseType,
        source_layer: SourceLayer = SourceLayer.NORMALIZED,
    ) -> None:
        self._doc_id = doc_id
        self._pack_id = pack_id
        self._role_id = role_id
        self._modality = modality
        self._container_type = container_type
        self._discourse_type = discourse_type
        self._source_layer = source_layer
        self._id_factory = _IdFactory(doc_id=doc_id)

        self._spans_by_id: dict[str, EvidenceSpan] = {}
        self._flags_by_id: dict[str, ReviewFlag] = {}
        self._actors_by_id: dict[str, ActorNode] = {}
        self._actor_edges: list[ActorEdge] = []
        self._sections_by_id: dict[str, SectionNode] = {}
        self._messages_by_id: dict[str, MessageNode] = {}
        self._thread_edges: list[ThreadEdge] = []
        self._time_anchors_by_id: dict[str, TimeAnchor] = {}
        self._chronology_edges: list[ChronologyEdge] = []
        self._evidence_edges: list[EvidenceEdge] = []
        self._packets_by_id: dict[str, PacketCandidate] = {}

        self._section_path_to_id: dict[tuple[str, ...], str] = {}
        self._section_root_id: str | None = None
        self._thread_id: str | None = None
        self._metadata: dict[str, Any] = {}

        self._section_span_links: dict[str, set[str]] = {}
        self._message_span_links: dict[str, set[str]] = {}
        self._actor_span_links: dict[str, set[str]] = {}
        self._section_children: dict[str, set[str]] = {}

        self._deferred_section_parents: list[tuple[str, str]] = []
        self._deferred_message_parent_edges: list[tuple[str, str]] = []
        self._deferred_packet_span_refs: list[tuple[str, tuple[str, ...]]] = []
        self._deferred_flag_span_refs: list[tuple[str, str]] = []
        self._deferred_span_message_refs: list[tuple[str, str]] = []
        self._deferred_span_time_anchor_refs: list[tuple[str, str]] = []
        self._deferred_span_prev_refs: list[tuple[str, str]] = []
        self._deferred_span_next_refs: list[tuple[str, str]] = []
        self._deferred_span_flag_refs: list[tuple[str, str]] = []
        self._deferred_message_section_refs: list[tuple[str, str]] = []
        self._deferred_message_time_anchor_refs: list[tuple[str, str]] = []
        self._deferred_message_span_refs: list[tuple[str, tuple[str, ...]]] = []
        self._deferred_packet_actor_refs: list[tuple[str, tuple[str, ...]]] = []
        self._deferred_packet_message_refs: list[tuple[str, tuple[str, ...]]] = []
        self._deferred_packet_time_anchor_refs: list[tuple[str, tuple[str, ...]]] = []
        self._deferred_chronology_edges: list[ChronologyEdge] = []
        self._deferred_evidence_edges: list[EvidenceEdge] = []
        self._deferred_thread_edges: list[ThreadEdge] = []

        self._diagnostics: list[str] = []
        self._actor_edge_signatures: set[tuple[str, str, str]] = set()
        self._thread_edge_signatures: set[tuple[str, str, str]] = set()
        self._chronology_edge_signatures: set[tuple[str, str, str]] = set()
        self._evidence_edge_signatures: set[tuple[str, str, str]] = set()

    def set_metadata(self, metadata: Mapping[str, Any]) -> "DocumentParseBuilder":
        self._metadata = dict(metadata)
        return self

    def set_section_root(self, section_id: str) -> "DocumentParseBuilder":
        if self._sections_by_id and section_id not in self._sections_by_id:
            raise MissingReferenceError(f"Unknown section root ID: {section_id}")
        self._section_root_id = section_id
        return self

    def set_thread_id(self, thread_id: str) -> "DocumentParseBuilder":
        if self._messages_by_id:
            existing = {node.thread_id for node in self._messages_by_id.values() if node.thread_id}
            if existing and thread_id not in existing:
                self._diag(
                    "thread_id_override",
                    f"Overriding thread id to {thread_id!r}; existing message thread ids={sorted(existing)}",
                )
        self._thread_id = thread_id
        return self

    def _diag(self, code: str, message: str) -> None:
        self._diagnostics.append(f"{code}: {message}")

    def _use_id(self, kind: str, object_id: str | None) -> str:
        if object_id is None:
            generated = self._id_factory.next(kind)
            self._diag("id_generated", f"generated {generated}")
            return generated
        value = object_id.strip()
        if not value:
            raise ValidationError(f"{kind} ID cannot be empty")
        _require_prefix(value, kind)
        return value

    def _can_defer(self, ref_kind: str) -> bool:
        return ref_kind in self._DEFERRED_REF_KINDS

    def add_span(
        self,
        *,
        span_id: str | None = None,
        text: str,
        normalized_text: str | None = None,
        char_range: CharRange | tuple[int, int] | None = None,
        bbox: BBox | tuple[float, float, float, float] | None = None,
        page_ref: PageRef | int | None = None,
        section_path: str | Sequence[str] | None = None,
        speaker_id: str | None = None,
        author_id: str | None = None,
        message_id: str | None = None,
        time_anchor_id: str | None = None,
        chronology_rank: int | None = None,
        authority_score: float = 0.0,
        source_layer: SourceLayer | None = None,
        review_flag_ids: Sequence[str] | None = None,
        evidence_kind: EvidenceKind = EvidenceKind.FACT,
        authority_class: AuthorityClass = AuthorityClass.UNKNOWN,
        cue_kinds: Sequence[Any] | None = None,
        previous_span_id: str | None = None,
        next_span_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> str:
        sid = self._use_id("span", span_id)
        if sid in self._spans_by_id:
            raise DuplicateIdError(f"Duplicate span ID: {sid}")
        if chronology_rank is not None and chronology_rank < 0:
            raise ValidationError("chronology_rank must be >= 0")
        _validate_score("authority_score", authority_score)

        pr: PageRef | None
        if isinstance(page_ref, PageRef):
            pr = page_ref
        elif isinstance(page_ref, int):
            pr = PageRef(page_index=page_ref)
        else:
            pr = None
        char_range_obj = _validate_char_range(char_range)
        bbox_obj = _validate_bbox(bbox, page_index=pr.page_index if pr else None)
        norm_text = normalized_text if normalized_text is not None else text
        span = EvidenceSpan(
            span_id=sid,
            text=text,
            normalized_text=norm_text,
            doc_id=self._doc_id,
            container_type=self._container_type,
            discourse_type=self._discourse_type,
            page_ref=pr,
            bbox=bbox_obj,
            char_range=char_range_obj,
            section_path=_normalize_section_path(section_path),
            speaker_id=speaker_id,
            author_id=author_id,
            message_id=message_id,
            time_anchor_id=time_anchor_id,
            chronology_rank=chronology_rank,
            authority_score=authority_score,
            source_layer=source_layer or self._source_layer,
            review_flag_ids=_freeze_tuple(review_flag_ids),
            evidence_kind=evidence_kind,
            authority_class=authority_class,
            cue_kinds=tuple(cue_kinds or ()),
            previous_span_id=previous_span_id,
            next_span_id=next_span_id,
            metadata=dict(metadata or {}),
        )
        if message_id and message_id not in self._messages_by_id:
            if self._can_defer("span.message"):
                self._deferred_span_message_refs.append((sid, message_id))
                self._diag("deferred_ref", f"deferred span.message {sid}->{message_id}")
            else:
                raise MissingReferenceError(f"Unknown message_id: {message_id}")
        if time_anchor_id and time_anchor_id not in self._time_anchors_by_id:
            if self._can_defer("span.time_anchor"):
                self._deferred_span_time_anchor_refs.append((sid, time_anchor_id))
                self._diag("deferred_ref", f"deferred span.time_anchor {sid}->{time_anchor_id}")
            else:
                raise MissingReferenceError(f"Unknown time_anchor_id: {time_anchor_id}")
        if previous_span_id and previous_span_id not in self._spans_by_id:
            if self._can_defer("span.previous"):
                self._deferred_span_prev_refs.append((sid, previous_span_id))
            else:
                raise MissingReferenceError(f"Unknown previous_span_id: {previous_span_id}")
        if next_span_id and next_span_id not in self._spans_by_id:
            if self._can_defer("span.next"):
                self._deferred_span_next_refs.append((sid, next_span_id))
            else:
                raise MissingReferenceError(f"Unknown next_span_id: {next_span_id}")
        for fid in span.review_flag_ids:
            if fid not in self._flags_by_id:
                if self._can_defer("span.review_flag"):
                    self._deferred_span_flag_refs.append((sid, fid))
                else:
                    raise MissingReferenceError(f"Unknown review_flag_id: {fid}")
        self._spans_by_id[sid] = span
        return sid

    def add_review_flag(
        self,
        *,
        flag_id: str | None = None,
        severity: ReviewSeverity | str,
        category: ReviewCategory | str,
        message: str,
        span_id: str | None = None,
        claim_id: str | None = None,
        field_path: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> str:
        fid = self._use_id("flag", flag_id)
        if fid in self._flags_by_id:
            raise DuplicateIdError(f"Duplicate flag ID: {fid}")
        sev = severity if isinstance(severity, ReviewSeverity) else ReviewSeverity(str(severity))
        cat = category if isinstance(category, ReviewCategory) else ReviewCategory(str(category))
        flag = ReviewFlag(
            flag_id=fid,
            severity=sev,
            category=cat,
            message=message,
            span_id=span_id,
            claim_id=claim_id,
            field_path=field_path,
            metadata=dict(metadata or {}),
        )
        self._flags_by_id[fid] = flag
        if span_id is not None and span_id not in self._spans_by_id:
            self._deferred_flag_span_refs.append((fid, span_id))
            self._diag("deferred_ref", f"deferred flag.span {fid}->{span_id}")
        return fid

    def add_actor(
        self,
        *,
        actor_id: str | None = None,
        display_name: str | None = None,
        role_label: str | None = None,
        email: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> str:
        aid = self._use_id("actor", actor_id)
        if aid in self._actors_by_id:
            raise DuplicateIdError(f"Duplicate actor ID: {aid}")
        merged_meta = dict(metadata or {})
        normalized_email = _normalize_email(email)
        if normalized_email:
            merged_meta["email"] = normalized_email
        self._actors_by_id[aid] = ActorNode(
            actor_id=aid,
            display_name=display_name,
            role_label=role_label,
            metadata=merged_meta,
        )
        return aid

    def _ensure_known_actor_ids(self, actor_ids: Sequence[str]) -> None:
        for actor_id in actor_ids:
            if actor_id not in self._actors_by_id:
                raise MissingReferenceError(f"Unknown actor_id: {actor_id}")

    def add_actor_edge(
        self,
        *,
        source_actor_id: str,
        target_actor_id: str,
        relation_type: RelationType | str,
        weight: float = 1.0,
        evidence_span_ids: Sequence[str] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        rel = _validate_relation_type(relation_type)
        self._ensure_known_actor_ids((source_actor_id, target_actor_id))
        span_tuple = _freeze_tuple(evidence_span_ids)
        missing_span_ids = self._missing_span_ids(span_tuple)
        if missing_span_ids:
            if self._can_defer("edge.actor_span"):
                self._diag(
                    "deferred_ref",
                    f"deferred actor_edge span refs {source_actor_id}->{target_actor_id} missing={list(missing_span_ids)}",
                )
            else:
                raise MissingReferenceError(f"Unknown span_ids: {sorted(missing_span_ids)}")
        sig = (source_actor_id, target_actor_id, rel.value)
        if sig in self._actor_edge_signatures:
            self._diag("duplicate_suppressed", f"actor_edge {sig} suppressed")
            return
        self._actor_edge_signatures.add(sig)
        self._actor_edges.append(
            ActorEdge(
                source_actor_id=source_actor_id,
                target_actor_id=target_actor_id,
                relation_type=rel,
                weight=weight,
                evidence_span_ids=span_tuple,
                metadata=dict(metadata or {}),
            )
        )

    def add_section(
        self,
        *,
        section_id: str | None = None,
        title: str | None = None,
        section_path: str | Sequence[str] | None = None,
        parent_section_id: str | None = None,
        child_section_ids: Sequence[str] | None = None,
        span_ids: Sequence[str] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> str:
        sid = self._use_id("section", section_id)
        if sid in self._sections_by_id:
            raise DuplicateIdError(f"Duplicate section ID: {sid}")
        path = _normalize_section_path(section_path)
        if path and path in self._section_path_to_id:
            raise ValidationError(f"Duplicate section_path: {path}")
        if path:
            self._section_path_to_id[path] = sid
        self._ensure_known_span_ids(span_ids or (), strict=False)
        section = SectionNode(
            section_id=sid,
            title=title,
            section_path=path,
            parent_section_id=parent_section_id,
            child_section_ids=_freeze_tuple(child_section_ids),
            span_ids=_freeze_tuple(span_ids),
            metadata=dict(metadata or {}),
        )
        self._sections_by_id[sid] = section
        if parent_section_id:
            if parent_section_id in self._sections_by_id:
                self._section_children.setdefault(parent_section_id, set()).add(sid)
            else:
                self._deferred_section_parents.append((sid, parent_section_id))
                self._diag("deferred_ref", f"deferred section.parent {sid}->{parent_section_id}")
        if child_section_ids:
            for child_id in child_section_ids:
                self._section_children.setdefault(sid, set()).add(child_id)
        return sid

    def add_message(
        self,
        *,
        message_id: str | None = None,
        thread_id: str | None = None,
        author_id: str | None = None,
        speaker_id: str | None = None,
        section_id: str | None = None,
        span_ids: Sequence[str] | None = None,
        time_anchor_id: str | None = None,
        parent_message_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> str:
        mid = self._use_id("message", message_id)
        if mid in self._messages_by_id:
            raise DuplicateIdError(f"Duplicate message ID: {mid}")
        if author_id is not None:
            self._ensure_known_actor_ids((author_id,))
        if speaker_id is not None:
            self._ensure_known_actor_ids((speaker_id,))
        if section_id is not None and section_id not in self._sections_by_id:
            if self._can_defer("message.section"):
                self._deferred_message_section_refs.append((mid, section_id))
                self._diag("deferred_ref", f"deferred message.section {mid}->{section_id}")
                section_id = None
            else:
                raise MissingReferenceError(f"Unknown section_id: {section_id}")
        if time_anchor_id is not None and time_anchor_id not in self._time_anchors_by_id:
            if self._can_defer("message.time_anchor"):
                self._deferred_message_time_anchor_refs.append((mid, time_anchor_id))
                self._diag("deferred_ref", f"deferred message.time_anchor {mid}->{time_anchor_id}")
                time_anchor_id = None
            else:
                raise MissingReferenceError(f"Unknown time_anchor_id: {time_anchor_id}")
        span_tuple = _freeze_tuple(span_ids)
        missing_span_ids = self._missing_span_ids(span_tuple)
        if missing_span_ids:
            if self._can_defer("message.span"):
                self._deferred_message_span_refs.append((mid, span_tuple))
                self._diag("deferred_ref", f"deferred message.span {mid} missing={list(missing_span_ids)}")
                span_tuple = ()
            else:
                raise MissingReferenceError(f"Unknown span_ids: {sorted(missing_span_ids)}")
        self._messages_by_id[mid] = MessageNode(
            message_id=mid,
            thread_id=thread_id,
            author_id=author_id,
            speaker_id=speaker_id,
            section_id=section_id,
            span_ids=span_tuple,
            time_anchor_id=time_anchor_id,
            metadata=dict(metadata or {}),
        )
        if self._thread_id is None:
            self._thread_id = thread_id
        if parent_message_id:
            if parent_message_id in self._messages_by_id:
                self.add_thread_edge(source_message_id=mid, target_message_id=parent_message_id, relation_type=RelationType.REPLIES_TO)
            else:
                self._deferred_message_parent_edges.append((mid, parent_message_id))
        return mid

    def _ensure_known_message_ids(self, message_ids: Sequence[str]) -> None:
        for message_id in message_ids:
            if message_id not in self._messages_by_id:
                raise MissingReferenceError(f"Unknown message_id: {message_id}")

    def add_thread_edge(
        self,
        *,
        source_message_id: str,
        target_message_id: str,
        relation_type: RelationType | str = RelationType.REPLIES_TO,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        edge = ThreadEdge(
            source_message_id=source_message_id,
            target_message_id=target_message_id,
            relation_type=_validate_relation_type(relation_type),
            metadata=dict(metadata or {}),
        )
        sig = (source_message_id, target_message_id, edge.relation_type.value)
        if sig in self._thread_edge_signatures:
            self._diag("duplicate_suppressed", f"thread_edge {sig} suppressed")
            return
        self._thread_edge_signatures.add(sig)
        if source_message_id in self._messages_by_id and target_message_id in self._messages_by_id:
            self._thread_edges.append(edge)
        else:
            self._deferred_thread_edges.append(edge)
            self._diag("deferred_ref", f"deferred edge.thread {source_message_id}->{target_message_id}")

    def add_time_anchor(
        self,
        *,
        time_anchor_id: str | None = None,
        label: str,
        iso8601: str | None = None,
        epoch_ms: int | None = None,
        sequence_rank: int | None = None,
        is_inferred: bool = False,
        metadata: Mapping[str, Any] | None = None,
    ) -> str:
        tid = self._use_id("time", time_anchor_id)
        if tid in self._time_anchors_by_id:
            raise DuplicateIdError(f"Duplicate time anchor ID: {tid}")
        if sequence_rank is not None and sequence_rank < 0:
            raise ValidationError("sequence_rank must be >= 0")
        if iso8601 is not None:
            try:
                datetime.fromisoformat(iso8601.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValidationError(f"Invalid iso8601 timestamp: {iso8601}") from exc
        self._time_anchors_by_id[tid] = TimeAnchor(
            time_anchor_id=tid,
            label=label,
            iso8601=iso8601,
            epoch_ms=epoch_ms,
            sequence_rank=sequence_rank,
            is_inferred=is_inferred,
            metadata=dict(metadata or {}),
        )
        return tid

    def _ensure_known_time_anchor_ids(self, anchor_ids: Sequence[str]) -> None:
        for anchor_id in anchor_ids:
            if anchor_id not in self._time_anchors_by_id:
                raise MissingReferenceError(f"Unknown time_anchor_id: {anchor_id}")

    def add_chronology_edge(
        self,
        *,
        source_time_anchor_id: str,
        target_time_anchor_id: str,
        relation_type: RelationType | str = RelationType.FOLLOWS,
        confidence: float = 1.0,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        _validate_score("chronology confidence", confidence)
        edge = ChronologyEdge(
            source_time_anchor_id=source_time_anchor_id,
            target_time_anchor_id=target_time_anchor_id,
            relation_type=_validate_relation_type(relation_type),
            confidence=confidence,
            metadata=dict(metadata or {}),
        )
        sig = (source_time_anchor_id, target_time_anchor_id, edge.relation_type.value)
        if sig in self._chronology_edge_signatures:
            self._diag("duplicate_suppressed", f"chronology_edge {sig} suppressed")
            return
        self._chronology_edge_signatures.add(sig)
        if source_time_anchor_id in self._time_anchors_by_id and target_time_anchor_id in self._time_anchors_by_id:
            if source_time_anchor_id == target_time_anchor_id:
                raise GraphIntegrityError("Chronology edges cannot self-loop")
            self._chronology_edges.append(edge)
        else:
            self._deferred_chronology_edges.append(edge)
            self._diag("deferred_ref", f"deferred edge.chronology {source_time_anchor_id}->{target_time_anchor_id}")

    def _missing_span_ids(self, span_ids: Sequence[str]) -> tuple[str, ...]:
        return tuple(sorted(span_id for span_id in span_ids if span_id not in self._spans_by_id))

    def _ensure_known_span_ids(self, span_ids: Sequence[str], *, strict: bool = True) -> None:
        missing = self._missing_span_ids(span_ids)
        if not missing:
            return
        if strict:
            raise MissingReferenceError(f"Unknown span_ids: {list(missing)}")
        self._diag("deferred_ref", f"non_strict span refs missing={list(missing)}")

    def add_evidence_edge(
        self,
        *,
        source_span_id: str,
        target_span_id: str,
        relation_type: RelationType | str,
        weight: float = 1.0,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        edge = EvidenceEdge(
            source_span_id=source_span_id,
            target_span_id=target_span_id,
            relation_type=_validate_relation_type(relation_type),
            weight=weight,
            metadata=dict(metadata or {}),
        )
        sig = (source_span_id, target_span_id, edge.relation_type.value)
        if sig in self._evidence_edge_signatures:
            self._diag("duplicate_suppressed", f"evidence_edge {sig} suppressed")
            return
        self._evidence_edge_signatures.add(sig)
        if source_span_id in self._spans_by_id and target_span_id in self._spans_by_id:
            self._evidence_edges.append(edge)
        else:
            self._deferred_evidence_edges.append(edge)
            self._diag("deferred_ref", f"deferred edge.evidence {source_span_id}->{target_span_id}")

    def add_packet(
        self,
        *,
        packet_id: str | None = None,
        packet_kind: PacketKind,
        span_ids: Sequence[str],
        primary_span_id: str | None = None,
        target_field_paths: Sequence[str] | None = None,
        target_claim_family_names: Sequence[str] | None = None,
        confidence: float = 0.0,
        authority_class: AuthorityClass = AuthorityClass.UNKNOWN,
        evidence_kind: EvidenceKind = EvidenceKind.CLAIM,
        review_flag_ids: Sequence[str] | None = None,
        actor_ids: Sequence[str] | None = None,
        message_ids: Sequence[str] | None = None,
        time_anchor_ids: Sequence[str] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> str:
        pid = self._use_id("packet", packet_id)
        if pid in self._packets_by_id:
            raise DuplicateIdError(f"Duplicate packet ID: {pid}")
        _validate_score("packet confidence", confidence)
        span_tuple = _freeze_tuple(span_ids)
        if not span_tuple:
            raise ValidationError("PacketCandidate must reference at least one span")
        if primary_span_id is not None and primary_span_id not in span_tuple:
            raise ValidationError("Packet primary_span_id must be included in span_ids")
        for flag_id in _freeze_tuple(review_flag_ids):
            if flag_id not in self._flags_by_id:
                raise MissingReferenceError(f"Unknown review flag ID: {flag_id}")
        actor_tuple = _freeze_tuple(actor_ids)
        message_tuple = _freeze_tuple(message_ids)
        time_tuple = _freeze_tuple(time_anchor_ids)
        if actor_tuple:
            unknown_actor_ids = tuple(sorted(actor_id for actor_id in actor_tuple if actor_id not in self._actors_by_id))
            if unknown_actor_ids:
                if self._can_defer("packet.actor"):
                    self._deferred_packet_actor_refs.append((pid, actor_tuple))
                    self._diag("deferred_ref", f"deferred packet.actor {pid} missing={list(unknown_actor_ids)}")
                else:
                    raise MissingReferenceError(f"Unknown actor_ids: {list(unknown_actor_ids)}")
        if message_tuple:
            unknown_message_ids = tuple(sorted(message_id for message_id in message_tuple if message_id not in self._messages_by_id))
            if unknown_message_ids:
                if self._can_defer("packet.message"):
                    self._deferred_packet_message_refs.append((pid, message_tuple))
                    self._diag("deferred_ref", f"deferred packet.message {pid} missing={list(unknown_message_ids)}")
                else:
                    raise MissingReferenceError(f"Unknown message_ids: {list(unknown_message_ids)}")
        if time_tuple:
            unknown_time_ids = tuple(sorted(time_id for time_id in time_tuple if time_id not in self._time_anchors_by_id))
            if unknown_time_ids:
                if self._can_defer("packet.time_anchor"):
                    self._deferred_packet_time_anchor_refs.append((pid, time_tuple))
                    self._diag("deferred_ref", f"deferred packet.time_anchor {pid} missing={list(unknown_time_ids)}")
                else:
                    raise MissingReferenceError(f"Unknown time_anchor_ids: {list(unknown_time_ids)}")
        packet_metadata = dict(metadata or {})
        if actor_tuple:
            packet_metadata["actor_ids"] = list(actor_tuple)
        if message_tuple:
            packet_metadata["message_ids"] = list(message_tuple)
        if time_tuple:
            packet_metadata["time_anchor_ids"] = list(time_tuple)
        packet = PacketCandidate(
            packet_id=pid,
            packet_kind=packet_kind,
            span_ids=span_tuple,
            primary_span_id=primary_span_id,
            target_field_paths=_freeze_tuple(target_field_paths),
            target_claim_family_names=_freeze_tuple(target_claim_family_names),
            confidence=confidence,
            authority_class=authority_class,
            evidence_kind=evidence_kind,
            review_flag_ids=_freeze_tuple(review_flag_ids),
            metadata=packet_metadata,
        )
        self._packets_by_id[pid] = packet
        if any(span_id not in self._spans_by_id for span_id in span_tuple):
            self._deferred_packet_span_refs.append((pid, span_tuple))
            self._diag("deferred_ref", f"deferred packet.span {pid}")
        return pid

    def attach_span_to_section(self, span_id: str, section_id: str) -> None:
        if section_id in self._sections_by_id and span_id in self._spans_by_id:
            self._diag("attach_immediate", f"span {span_id} attached to section {section_id}")
        elif section_id in self._sections_by_id and span_id not in self._spans_by_id:
            if not self._can_defer("attach.section_span"):
                raise MissingReferenceError(f"Unknown span_id in attach_span_to_section: {span_id}")
            self._diag("deferred_ref", f"deferred attach.section_span {section_id}->{span_id}")
        elif section_id not in self._sections_by_id:
            if not self._can_defer("attach.section_span"):
                raise MissingReferenceError(f"Unknown section_id in attach_span_to_section: {section_id}")
            self._diag("deferred_ref", f"deferred attach.section_span {section_id}->{span_id}")
        self._section_span_links.setdefault(section_id, set()).add(span_id)

    def attach_message_to_spans(self, message_id: str, span_ids: Sequence[str]) -> None:
        frozen = _freeze_tuple(span_ids)
        if message_id in self._messages_by_id:
            missing = self._missing_span_ids(frozen)
            if missing and not self._can_defer("attach.message_span"):
                raise MissingReferenceError(f"Unknown span_ids in attach_message_to_spans: {list(missing)}")
            if missing:
                self._diag("deferred_ref", f"deferred attach.message_span {message_id} missing={list(missing)}")
        elif not self._can_defer("attach.message_span"):
            raise MissingReferenceError(f"Unknown message_id in attach_message_to_spans: {message_id}")
        self._message_span_links.setdefault(message_id, set()).update(_freeze_tuple(span_ids))

    def attach_actor_to_spans(self, actor_id: str, span_ids: Sequence[str]) -> None:
        frozen = _freeze_tuple(span_ids)
        if actor_id in self._actors_by_id:
            missing = self._missing_span_ids(frozen)
            if missing and not self._can_defer("attach.actor_span"):
                raise MissingReferenceError(f"Unknown span_ids in attach_actor_to_spans: {list(missing)}")
            if missing:
                self._diag("deferred_ref", f"deferred attach.actor_span {actor_id} missing={list(missing)}")
        elif not self._can_defer("attach.actor_span"):
            raise MissingReferenceError(f"Unknown actor_id in attach_actor_to_spans: {actor_id}")
        self._actor_span_links.setdefault(actor_id, set()).update(_freeze_tuple(span_ids))

    def _resolve_deferred(self) -> None:
        # Section parent links.
        unresolved_sections: list[tuple[str, str]] = []
        for child_id, parent_id in self._deferred_section_parents:
            if child_id in self._sections_by_id and parent_id in self._sections_by_id:
                child = self._sections_by_id[child_id]
                self._sections_by_id[child_id] = replace(child, parent_section_id=parent_id)
                self._section_children.setdefault(parent_id, set()).add(child_id)
            else:
                unresolved_sections.append((child_id, parent_id))
        if unresolved_sections:
            raise MissingReferenceError(f"Unresolved section parent refs: {unresolved_sections}")

        # Message parent links through reply edges.
        unresolved_message_parents: list[tuple[str, str]] = []
        for child_id, parent_id in self._deferred_message_parent_edges:
            if child_id in self._messages_by_id and parent_id in self._messages_by_id:
                self._thread_edges.append(
                    ThreadEdge(
                        source_message_id=child_id,
                        target_message_id=parent_id,
                        relation_type=RelationType.REPLIES_TO,
                        metadata={},
                    )
                )
            else:
                unresolved_message_parents.append((child_id, parent_id))
        if unresolved_message_parents:
            raise MissingReferenceError(f"Unresolved message parent refs: {unresolved_message_parents}")

        unresolved_thread_edges: list[ThreadEdge] = []
        for edge in self._deferred_thread_edges:
            if edge.source_message_id in self._messages_by_id and edge.target_message_id in self._messages_by_id:
                self._thread_edges.append(edge)
            else:
                unresolved_thread_edges.append(edge)
        if unresolved_thread_edges:
            raise MissingReferenceError(
                "Unresolved thread edge references: "
                + ", ".join(f"{e.source_message_id}->{e.target_message_id}" for e in unresolved_thread_edges)
            )

        unresolved_chronology: list[ChronologyEdge] = []
        for edge in self._deferred_chronology_edges:
            if edge.source_time_anchor_id in self._time_anchors_by_id and edge.target_time_anchor_id in self._time_anchors_by_id:
                self._chronology_edges.append(edge)
            else:
                unresolved_chronology.append(edge)
        if unresolved_chronology:
            raise MissingReferenceError(
                "Unresolved chronology edge references: "
                + ", ".join(f"{e.source_time_anchor_id}->{e.target_time_anchor_id}" for e in unresolved_chronology)
            )

        unresolved_evidence: list[EvidenceEdge] = []
        for edge in self._deferred_evidence_edges:
            if edge.source_span_id in self._spans_by_id and edge.target_span_id in self._spans_by_id:
                self._evidence_edges.append(edge)
            else:
                unresolved_evidence.append(edge)
        if unresolved_evidence:
            raise MissingReferenceError(
                "Unresolved evidence edge references: "
                + ", ".join(f"{e.source_span_id}->{e.target_span_id}" for e in unresolved_evidence)
            )

        for flag_id, span_id in self._deferred_flag_span_refs:
            if span_id not in self._spans_by_id:
                raise MissingReferenceError(f"Review flag {flag_id} references unknown span_id: {span_id}")
            self._diag("deferred_resolved", f"flag.span {flag_id}->{span_id}")

        for span_id, message_id in self._deferred_span_message_refs:
            if message_id not in self._messages_by_id:
                raise MissingReferenceError(f"Span {span_id} references unknown message_id: {message_id}")
            span = self._spans_by_id[span_id]
            self._spans_by_id[span_id] = replace(span, message_id=message_id)
            self._diag("deferred_resolved", f"span.message {span_id}->{message_id}")

        for span_id, time_anchor_id in self._deferred_span_time_anchor_refs:
            if time_anchor_id not in self._time_anchors_by_id:
                raise MissingReferenceError(f"Span {span_id} references unknown time_anchor_id: {time_anchor_id}")
            span = self._spans_by_id[span_id]
            self._spans_by_id[span_id] = replace(span, time_anchor_id=time_anchor_id)
            self._diag("deferred_resolved", f"span.time_anchor {span_id}->{time_anchor_id}")

        for span_id, previous_span_id in self._deferred_span_prev_refs:
            if previous_span_id not in self._spans_by_id:
                raise MissingReferenceError(f"Span {span_id} references unknown previous_span_id: {previous_span_id}")
            span = self._spans_by_id[span_id]
            self._spans_by_id[span_id] = replace(span, previous_span_id=previous_span_id)

        for span_id, next_span_id in self._deferred_span_next_refs:
            if next_span_id not in self._spans_by_id:
                raise MissingReferenceError(f"Span {span_id} references unknown next_span_id: {next_span_id}")
            span = self._spans_by_id[span_id]
            self._spans_by_id[span_id] = replace(span, next_span_id=next_span_id)

        for span_id, flag_id in self._deferred_span_flag_refs:
            if flag_id not in self._flags_by_id:
                raise MissingReferenceError(f"Span {span_id} references unknown review_flag_id: {flag_id}")
            span = self._spans_by_id[span_id]
            self._spans_by_id[span_id] = replace(span, review_flag_ids=_freeze_tuple((*span.review_flag_ids, flag_id)))

        for packet_id, span_ids in self._deferred_packet_span_refs:
            for span_id in span_ids:
                if span_id not in self._spans_by_id:
                    raise MissingReferenceError(f"Packet {packet_id} references unknown span_id: {span_id}")
            self._diag("deferred_resolved", f"packet.span {packet_id}")

        for message_id, section_id in self._deferred_message_section_refs:
            if section_id not in self._sections_by_id:
                raise MissingReferenceError(f"Message {message_id} references unknown section_id: {section_id}")
            message = self._messages_by_id[message_id]
            self._messages_by_id[message_id] = replace(message, section_id=section_id)

        for message_id, time_anchor_id in self._deferred_message_time_anchor_refs:
            if time_anchor_id not in self._time_anchors_by_id:
                raise MissingReferenceError(f"Message {message_id} references unknown time_anchor_id: {time_anchor_id}")
            message = self._messages_by_id[message_id]
            self._messages_by_id[message_id] = replace(message, time_anchor_id=time_anchor_id)

        for message_id, span_ids in self._deferred_message_span_refs:
            missing = self._missing_span_ids(span_ids)
            if missing:
                raise MissingReferenceError(f"Message {message_id} references unknown span_ids: {list(missing)}")
            message = self._messages_by_id[message_id]
            self._messages_by_id[message_id] = replace(message, span_ids=_freeze_tuple((*message.span_ids, *span_ids)))

        for packet_id, actor_ids in self._deferred_packet_actor_refs:
            unknown = [actor_id for actor_id in actor_ids if actor_id not in self._actors_by_id]
            if unknown:
                raise MissingReferenceError(f"Packet {packet_id} references unknown actor_ids: {unknown}")

        for packet_id, message_ids in self._deferred_packet_message_refs:
            unknown = [message_id for message_id in message_ids if message_id not in self._messages_by_id]
            if unknown:
                raise MissingReferenceError(f"Packet {packet_id} references unknown message_ids: {unknown}")

        for packet_id, time_anchor_ids in self._deferred_packet_time_anchor_refs:
            unknown = [time_anchor_id for time_anchor_id in time_anchor_ids if time_anchor_id not in self._time_anchors_by_id]
            if unknown:
                raise MissingReferenceError(f"Packet {packet_id} references unknown time_anchor_ids: {unknown}")

    def _apply_link_attachments(self) -> None:
        # Section span attachments.
        for section_id, span_set in self._section_span_links.items():
            if section_id not in self._sections_by_id:
                raise MissingReferenceError(f"Unknown section_id in attach_span_to_section: {section_id}")
            self._ensure_known_span_ids(tuple(sorted(span_set)))
            section = self._sections_by_id[section_id]
            merged_spans = _freeze_tuple((*section.span_ids, *sorted(span_set)))
            self._sections_by_id[section_id] = replace(section, span_ids=merged_spans)

        # Message span attachments.
        for message_id, span_set in self._message_span_links.items():
            if message_id not in self._messages_by_id:
                raise MissingReferenceError(f"Unknown message_id in attach_message_to_spans: {message_id}")
            self._ensure_known_span_ids(tuple(sorted(span_set)))
            message = self._messages_by_id[message_id]
            merged_spans = _freeze_tuple((*message.span_ids, *sorted(span_set)))
            self._messages_by_id[message_id] = replace(message, span_ids=merged_spans)

        # Actor span attachments are stored in actor metadata.
        for actor_id, span_set in self._actor_span_links.items():
            if actor_id not in self._actors_by_id:
                raise MissingReferenceError(f"Unknown actor_id in attach_actor_to_spans: {actor_id}")
            self._ensure_known_span_ids(tuple(sorted(span_set)))
            actor = self._actors_by_id[actor_id]
            updated_metadata = dict(actor.metadata)
            existing = updated_metadata.get("span_ids")
            existing_ids = _freeze_tuple(existing) if isinstance(existing, (list, tuple)) else ()
            updated_metadata["span_ids"] = list(_freeze_tuple((*existing_ids, *sorted(span_set))))
            self._actors_by_id[actor_id] = replace(actor, metadata=updated_metadata)

        # Ensure parent -> child links are reflected on section nodes.
        for parent_id, children in self._section_children.items():
            if parent_id not in self._sections_by_id:
                raise MissingReferenceError(f"Unknown section parent ID: {parent_id}")
            for child_id in children:
                if child_id not in self._sections_by_id:
                    raise MissingReferenceError(f"Unknown section child ID: {child_id}")
            parent = self._sections_by_id[parent_id]
            merged_children = _freeze_tuple((*parent.child_section_ids, *sorted(children)))
            self._sections_by_id[parent_id] = replace(parent, child_section_ids=merged_children)

    def _validate_integrity(self) -> None:
        # Packet references.
        for packet in self._packets_by_id.values():
            self._ensure_known_span_ids(packet.span_ids)
            if packet.primary_span_id and packet.primary_span_id not in self._spans_by_id:
                raise MissingReferenceError(f"Packet {packet.packet_id} has unknown primary_span_id")
            for flag_id in packet.review_flag_ids:
                if flag_id not in self._flags_by_id:
                    raise MissingReferenceError(f"Packet {packet.packet_id} references unknown flag_id {flag_id}")

        # Span references.
        for span in self._spans_by_id.values():
            if span.previous_span_id and span.previous_span_id not in self._spans_by_id:
                raise MissingReferenceError(f"Span {span.span_id} has unknown previous_span_id")
            if span.next_span_id and span.next_span_id not in self._spans_by_id:
                raise MissingReferenceError(f"Span {span.span_id} has unknown next_span_id")
            if span.speaker_id and span.speaker_id not in self._actors_by_id:
                raise MissingReferenceError(f"Span {span.span_id} has unknown speaker_id")
            if span.author_id and span.author_id not in self._actors_by_id:
                raise MissingReferenceError(f"Span {span.span_id} has unknown author_id")
            if span.message_id and span.message_id not in self._messages_by_id:
                raise MissingReferenceError(f"Span {span.span_id} has unknown message_id")
            if span.time_anchor_id and span.time_anchor_id not in self._time_anchors_by_id:
                raise MissingReferenceError(f"Span {span.span_id} has unknown time_anchor_id")

        # Flags referencing spans.
        for flag in self._flags_by_id.values():
            if flag.span_id and flag.span_id not in self._spans_by_id:
                raise MissingReferenceError(f"Flag {flag.flag_id} has unknown span_id")

        # Sections.
        for section in self._sections_by_id.values():
            if section.parent_section_id and section.parent_section_id not in self._sections_by_id:
                raise MissingReferenceError(f"Section {section.section_id} has unknown parent_section_id")
            self._ensure_known_span_ids(section.span_ids)
            for child_id in section.child_section_ids:
                if child_id not in self._sections_by_id:
                    raise MissingReferenceError(f"Section {section.section_id} has unknown child_section_id")

        # Messages.
        for message in self._messages_by_id.values():
            if message.author_id and message.author_id not in self._actors_by_id:
                raise MissingReferenceError(f"Message {message.message_id} has unknown author_id")
            if message.speaker_id and message.speaker_id not in self._actors_by_id:
                raise MissingReferenceError(f"Message {message.message_id} has unknown speaker_id")
            if message.section_id and message.section_id not in self._sections_by_id:
                raise MissingReferenceError(f"Message {message.message_id} has unknown section_id")
            if message.time_anchor_id and message.time_anchor_id not in self._time_anchors_by_id:
                raise MissingReferenceError(f"Message {message.message_id} has unknown time_anchor_id")
            self._ensure_known_span_ids(message.span_ids)

        # Thread, chronology, evidence edges.
        self._ensure_known_actor_ids(tuple(edge.source_actor_id for edge in self._actor_edges))
        self._ensure_known_actor_ids(tuple(edge.target_actor_id for edge in self._actor_edges))
        for edge in self._actor_edges:
            self._ensure_known_span_ids(edge.evidence_span_ids)
        for edge in self._thread_edges:
            self._ensure_known_message_ids((edge.source_message_id, edge.target_message_id))
        for edge in self._chronology_edges:
            if edge.source_time_anchor_id == edge.target_time_anchor_id:
                raise GraphIntegrityError("Chronology edge self-loop detected")
            self._ensure_known_time_anchor_ids((edge.source_time_anchor_id, edge.target_time_anchor_id))
        for edge in self._evidence_edges:
            self._ensure_known_span_ids((edge.source_span_id, edge.target_span_id))

        self._validate_section_tree_cycles()
        self._validate_thread_cycles()
        self._validate_chronology_cycles()

    def _validate_section_tree_cycles(self) -> None:
        graph: dict[str, list[str]] = defaultdict(list)
        for section in self._sections_by_id.values():
            if section.parent_section_id:
                graph[section.parent_section_id].append(section.section_id)
        self._ensure_acyclic(graph, "section_tree")

    def _validate_thread_cycles(self) -> None:
        graph: dict[str, list[str]] = defaultdict(list)
        for edge in self._thread_edges:
            if edge.relation_type in {RelationType.REPLIES_TO, RelationType.FOLLOWS}:
                graph[edge.source_message_id].append(edge.target_message_id)
        self._ensure_acyclic(graph, "thread_graph")

    def _validate_chronology_cycles(self) -> None:
        graph: dict[str, list[str]] = defaultdict(list)
        for edge in self._chronology_edges:
            if edge.relation_type in {RelationType.FOLLOWS, RelationType.REFERENCES}:
                graph[edge.source_time_anchor_id].append(edge.target_time_anchor_id)
        self._ensure_acyclic(graph, "chronology_graph")

    def _ensure_acyclic(self, graph: Mapping[str, Sequence[str]], label: str) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()

        def dfs(node: str) -> None:
            if node in visited:
                return
            if node in visiting:
                raise GraphIntegrityError(f"Cycle detected in {label} at node {node}")
            visiting.add(node)
            for nxt in graph.get(node, ()):
                dfs(nxt)
            visiting.remove(node)
            visited.add(node)

        for node in graph:
            dfs(node)

    def build(self) -> DocumentParse:
        self._resolve_deferred()
        self._apply_link_attachments()
        self._validate_integrity()

        actor_graph = ActorGraph(
            nodes=tuple(sorted(self._actors_by_id.values(), key=lambda node: node.actor_id)),
            edges=tuple(
                sorted(
                    self._actor_edges,
                    key=lambda edge: (edge.source_actor_id, edge.target_actor_id, edge.relation_type.value),
                )
            ),
        )
        section_tree = SectionTree(
            nodes=tuple(sorted(self._sections_by_id.values(), key=lambda node: (len(node.section_path), node.section_path, node.section_id))),
            root_section_id=self._section_root_id,
        )
        thread_graph = None
        if self._messages_by_id or self._thread_edges:
            thread_graph = ThreadGraph(
                thread_id=self._thread_id or f"thread:{self._doc_id}:000001",
                message_nodes=tuple(sorted(self._messages_by_id.values(), key=lambda node: node.message_id)),
                edges=tuple(
                    sorted(
                        self._thread_edges,
                        key=lambda edge: (edge.source_message_id, edge.target_message_id, edge.relation_type.value),
                    )
                ),
            )
        chronology_graph = ChronologyGraph(
            time_anchors=tuple(
                sorted(
                    self._time_anchors_by_id.values(),
                    key=lambda anchor: (
                        anchor.sequence_rank if anchor.sequence_rank is not None else 10**9,
                        anchor.time_anchor_id,
                    ),
                )
            ),
            edges=tuple(
                sorted(
                    self._chronology_edges,
                    key=lambda edge: (edge.source_time_anchor_id, edge.target_time_anchor_id, edge.relation_type.value),
                )
            ),
        )
        evidence_graph = EvidenceGraph(
            edges=tuple(
                sorted(
                    self._evidence_edges,
                    key=lambda edge: (edge.source_span_id, edge.target_span_id, edge.relation_type.value),
                )
            )
        )
        metadata = dict(self._metadata)
        if self._diagnostics:
            metadata["builder_diagnostics"] = list(self._diagnostics)
        return DocumentParse(
            doc_id=self._doc_id,
            pack_id=self._pack_id,
            role_id=self._role_id,
            modality=self._modality,
            container_type=self._container_type,
            discourse_type=self._discourse_type,
            source_layer=self._source_layer,
            evidence_spans=tuple(
                sorted(
                    self._spans_by_id.values(),
                    key=lambda span: (
                        span.chronology_rank if span.chronology_rank is not None else 10**9,
                        span.span_id,
                    ),
                )
            ),
            review_flags=tuple(sorted(self._flags_by_id.values(), key=lambda flag: flag.flag_id)),
            actor_graph=actor_graph,
            section_tree=section_tree,
            thread_graph=thread_graph,
            chronology_graph=chronology_graph,
            evidence_graph=evidence_graph,
            packet_candidates=tuple(sorted(self._packets_by_id.values(), key=lambda packet: packet.packet_id)),
            metadata=metadata,
        )

    def builder_state_summary(self) -> dict[str, int]:
        return {
            "spans": len(self._spans_by_id),
            "review_flags": len(self._flags_by_id),
            "actors": len(self._actors_by_id),
            "actor_edges": len(self._actor_edges),
            "sections": len(self._sections_by_id),
            "messages": len(self._messages_by_id),
            "thread_edges": len(self._thread_edges),
            "time_anchors": len(self._time_anchors_by_id),
            "chronology_edges": len(self._chronology_edges),
            "evidence_edges": len(self._evidence_edges),
            "packets": len(self._packets_by_id),
            "diagnostics": len(self._diagnostics),
        }

    def to_debug_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self._doc_id,
            "pack_id": self._pack_id,
            "role_id": self._role_id,
            "modality": self._modality,
            "container_type": self._container_type.value,
            "discourse_type": self._discourse_type.value,
            "source_layer": self._source_layer.value,
            "state_summary": self.builder_state_summary(),
            "deferred_counts": {
                "section_parent": len(self._deferred_section_parents),
                "message_parent": len(self._deferred_message_parent_edges),
                "packet_span": len(self._deferred_packet_span_refs),
                "flag_span": len(self._deferred_flag_span_refs),
                "thread_edges": len(self._deferred_thread_edges),
                "chronology_edges": len(self._deferred_chronology_edges),
                "evidence_edges": len(self._deferred_evidence_edges),
            },
            "diagnostics": list(self._diagnostics),
        }
