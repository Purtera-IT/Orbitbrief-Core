from __future__ import annotations

from dataclasses import dataclass

BBox = tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class RoomDeviceAssociation:
    associated: bool
    score: float
    reasons: tuple[str, ...]


def _center(bbox: BBox) -> tuple[float, float]:
    return ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)


def _distance(a: BBox, b: BBox) -> float:
    ax, ay = _center(a)
    bx, by = _center(b)
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5


def score_room_device_association(
    symbol_bbox: BBox | None,
    room_label_bboxes: list[BBox],
    *,
    same_region: bool = False,
    same_subregion: bool = False,
    same_pseudo_page: bool = False,
    same_detail_frame: bool = False,
    leader_attached: bool = False,
) -> RoomDeviceAssociation:
    if symbol_bbox is None:
        return RoomDeviceAssociation(False, 0.0, ("missing_symbol_bbox",))

    score = 0.0
    reasons: list[str] = []
    if room_label_bboxes:
        nearest = min(_distance(symbol_bbox, room_bbox) for room_bbox in room_label_bboxes)
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
    score = min(1.0, score)
    return RoomDeviceAssociation(score >= 0.55, score, tuple(reasons))
