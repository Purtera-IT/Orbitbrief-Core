from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PacketFamilyPolicy:
    family: str
    max_support_spans: int
    max_cross_section_distance: int
    allow_quoted_support: bool
    allow_forwarded_support: bool
    min_support_authority: float
    min_anchor_score: float
    sparse_support_tolerance: bool = False


_POLICIES: tuple[PacketFamilyPolicy, ...] = (
    PacketFamilyPolicy("scope_packet", max_support_spans=7, max_cross_section_distance=1, allow_quoted_support=False, allow_forwarded_support=False, min_support_authority=0.55, min_anchor_score=0.45),
    PacketFamilyPolicy("exclusion_packet", max_support_spans=6, max_cross_section_distance=1, allow_quoted_support=True, allow_forwarded_support=False, min_support_authority=0.5, min_anchor_score=0.44),
    PacketFamilyPolicy("assumption_packet", max_support_spans=6, max_cross_section_distance=1, allow_quoted_support=True, allow_forwarded_support=False, min_support_authority=0.5, min_anchor_score=0.44),
    PacketFamilyPolicy("risk_packet", max_support_spans=8, max_cross_section_distance=2, allow_quoted_support=True, allow_forwarded_support=False, min_support_authority=0.45, min_anchor_score=0.42, sparse_support_tolerance=True),
    PacketFamilyPolicy("dependency_packet", max_support_spans=7, max_cross_section_distance=2, allow_quoted_support=True, allow_forwarded_support=True, min_support_authority=0.45, min_anchor_score=0.42),
    PacketFamilyPolicy("site_packet", max_support_spans=6, max_cross_section_distance=2, allow_quoted_support=True, allow_forwarded_support=True, min_support_authority=0.45, min_anchor_score=0.4),
    PacketFamilyPolicy("quantity_packet", max_support_spans=5, max_cross_section_distance=2, allow_quoted_support=True, allow_forwarded_support=True, min_support_authority=0.45, min_anchor_score=0.4),
    PacketFamilyPolicy("deliverable_packet", max_support_spans=7, max_cross_section_distance=1, allow_quoted_support=False, allow_forwarded_support=False, min_support_authority=0.6, min_anchor_score=0.48),
    PacketFamilyPolicy("schedule_packet", max_support_spans=7, max_cross_section_distance=2, allow_quoted_support=True, allow_forwarded_support=True, min_support_authority=0.5, min_anchor_score=0.44),
    PacketFamilyPolicy("responsibility_packet", max_support_spans=6, max_cross_section_distance=1, allow_quoted_support=False, allow_forwarded_support=False, min_support_authority=0.58, min_anchor_score=0.47),
    PacketFamilyPolicy("open_question_packet", max_support_spans=5, max_cross_section_distance=2, allow_quoted_support=True, allow_forwarded_support=True, min_support_authority=0.4, min_anchor_score=0.38, sparse_support_tolerance=True),
    PacketFamilyPolicy("drawing_metadata_packet", max_support_spans=8, max_cross_section_distance=1, allow_quoted_support=True, allow_forwarded_support=True, min_support_authority=0.45, min_anchor_score=0.38),
    PacketFamilyPolicy("site_identity_packet", max_support_spans=7, max_cross_section_distance=2, allow_quoted_support=True, allow_forwarded_support=True, min_support_authority=0.45, min_anchor_score=0.4),
    PacketFamilyPolicy("network_room_or_closet_packet", max_support_spans=6, max_cross_section_distance=2, allow_quoted_support=True, allow_forwarded_support=True, min_support_authority=0.45, min_anchor_score=0.4),
    PacketFamilyPolicy("equipment_reference_packet", max_support_spans=7, max_cross_section_distance=2, allow_quoted_support=True, allow_forwarded_support=True, min_support_authority=0.45, min_anchor_score=0.4),
    PacketFamilyPolicy("note_scope_packet", max_support_spans=8, max_cross_section_distance=2, allow_quoted_support=True, allow_forwarded_support=True, min_support_authority=0.4, min_anchor_score=0.38),
    PacketFamilyPolicy("revision_change_packet", max_support_spans=5, max_cross_section_distance=1, allow_quoted_support=False, allow_forwarded_support=False, min_support_authority=0.5, min_anchor_score=0.42),
    PacketFamilyPolicy("topology_hint_packet", max_support_spans=6, max_cross_section_distance=3, allow_quoted_support=True, allow_forwarded_support=True, min_support_authority=0.4, min_anchor_score=0.38, sparse_support_tolerance=True),
    PacketFamilyPolicy("constructability_packet", max_support_spans=7, max_cross_section_distance=2, allow_quoted_support=True, allow_forwarded_support=True, min_support_authority=0.45, min_anchor_score=0.4),
    PacketFamilyPolicy("known_quantity_packet", max_support_spans=6, max_cross_section_distance=2, allow_quoted_support=True, allow_forwarded_support=True, min_support_authority=0.4, min_anchor_score=0.38),
)

PACKET_POLICIES: dict[str, PacketFamilyPolicy] = {policy.family: policy for policy in _POLICIES}

DEFAULT_PACKET_POLICY = PacketFamilyPolicy(
    "default_packet",
    max_support_spans=6,
    max_cross_section_distance=1,
    allow_quoted_support=False,
    allow_forwarded_support=False,
    min_support_authority=0.5,
    min_anchor_score=0.45,
)


def get_packet_policy(family: str) -> PacketFamilyPolicy:
    return PACKET_POLICIES.get(family, DEFAULT_PACKET_POLICY)
