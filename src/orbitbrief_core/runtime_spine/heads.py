from __future__ import annotations

from pathlib import Path


def _flag(code: str, message: str, *, requires_32b: bool = False) -> dict:
    return {
        "code": code,
        "message": message,
        "requires_32b": requires_32b,
    }


def integrity_head(path: Path) -> dict:
    if not path.exists():
        return {"status": "failed", "review_flags": [_flag("missing_file", f"File not found: {path}")]}
    return {"status": "ok", "review_flags": []}


def modality_head(path: Path) -> dict:
    suffix = path.suffix.lower()
    mapping = {
        ".txt": "txt",
        ".md": "md",
        ".docx": "docx",
        ".csv": "csv",
        ".xlsx": "xlsx",
        ".xls": "xls",
        ".pdf": "pdf",
        ".esx": "esx",
        ".zip": "zip",
    }
    return {"status": "ok", "modality": mapping.get(suffix, suffix.lstrip("."))}


def role_head(path: Path, modality: str) -> dict:
    name = path.stem.lower()
    modality = modality.lower()
    if modality in {"esx", "zip"}:
        role_id = "wireless_survey_packet"
    elif modality in {"csv", "xlsx", "xls"}:
        if "camera" in name or "surveillance" in name:
            role_id = "camera_schedule_surveillance"
        elif "bom" in name or "equipment" in name:
            role_id = "bom_equipment_schedule"
        else:
            role_id = "site_roster_spreadsheet"
    elif modality == "pdf":
        role_id = "drawing_packet"
    else:
        role_id = "transcript_or_notes"
    return {"status": "implemented", "role_id": role_id}


def complexity_head(path: Path, role_id: str, modality: str) -> dict:
    needs_32b = role_id in {"drawing_packet", "wireless_survey_packet"} or modality.lower() in {"pdf", "zip", "esx"}
    flags = [_flag("needs_32b_policy", f"{role_id} requires 32b/local review path", requires_32b=True)] if needs_32b else []
    return {"status": "ok", "needs_32b_policy": needs_32b, "review_flags": flags}


def review_calibrator(integrity_result: dict, role_result: dict, complexity_result: dict, extra_review_flags: list) -> dict:
    if integrity_result.get("status") != "ok":
        return {"decision": "needs_human_review", "review_flags": integrity_result.get("review_flags", [])}
    if role_result.get("status") == "parked":
        return {"decision": "parked", "review_flags": extra_review_flags}
    if complexity_result.get("needs_32b_policy"):
        return {
            "decision": "needs_32b",
            "review_flags": [*complexity_result.get("review_flags", []), *extra_review_flags],
        }
    if extra_review_flags:
        return {"decision": "needs_human_review", "review_flags": list(extra_review_flags)}
    return {"decision": "proceed", "review_flags": []}


__all__ = [
    "complexity_head",
    "integrity_head",
    "modality_head",
    "review_calibrator",
    "role_head",
]
