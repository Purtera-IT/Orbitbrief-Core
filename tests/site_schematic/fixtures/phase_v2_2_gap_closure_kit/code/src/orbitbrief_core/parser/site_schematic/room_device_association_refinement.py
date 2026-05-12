from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple


BBox = Tuple[float, float, float, float]


@dataclass
class RoomDeviceAssociation:
    associated: bool
    score: float
    reasons: List[str]


def _center(b: BBox) -> Tuple[float, float]:
    return ((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0)


def _dist(a: BBox, b: BBox) -> float:
    ax, ay = _center(a)
    bx, by = _center(b)
    return ((ax-bx)**2 + (ay-by)**2) ** 0.5


def score_room_device_association(
    symbol_bbox: Optional[BBox],
    room_label_bboxes: Iterable[BBox],
    *,
    same_region: bool = False,
    same_subregion: bool = False,
    same_pseudo_page: bool = False,
    same_detail_frame: bool = False,
    leader_attached: bool = False,
) -> RoomDeviceAssociation:
    if symbol_bbox is None:
        return RoomDeviceAssociation(False, 0.0, ["missing_symbol_bbox"])

    reasons: List[str] = []
    score = 0.0

    room_label_bboxes = list(room_label_bboxes)
    if room_label_bboxes:
        nearest = min(_dist(symbol_bbox, rb) for rb in room_label_bboxes)
        if nearest <= 120:
            score += 0.35
            reasons.append("near_room_label")
        elif nearest <= 240:
            score += 0.15
            reasons.append("room_label_within_context")

    if same_region:
        score += 0.15
        reasons.append("same_region")
    if same_subregion:
        score += 0.15
        reasons.append("same_subregion")
    if same_pseudo_page:
        score += 0.15
        reasons.append("same_pseudo_page")
    if same_detail_frame:
        score += 0.1
        reasons.append("same_detail_frame")
    if leader_attached:
        score += 0.1
        reasons.append("leader_attached")

    return RoomDeviceAssociation(score >= 0.55, min(score, 1.0), reasons)
