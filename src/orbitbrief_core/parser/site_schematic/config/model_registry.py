from __future__ import annotations

import os
from pathlib import Path
from typing import Any
import importlib.util

import yaml


def _candidate_paths() -> tuple[Path, ...]:
    here = Path(__file__).resolve()
    candidates: list[Path] = []
    for parent in here.parents:
        candidates.append(parent / "config" / "runtime" / "site_schematic_models.yaml")
        candidates.append(parent / "config" / "runtime" / "parsers" / "site_schematic_models.yaml")
    # preserve order while deduping
    seen: set[Path] = set()
    ordered: list[Path] = []
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        ordered.append(path)
    return tuple(ordered)


def load_site_schematic_model_registry() -> dict[str, Any]:
    for path in _candidate_paths():
        if not path.exists():
            continue
        data = yaml.safe_load(path.read_text()) or {}
        resolved: dict[str, Any] = {}
        for key, value in dict(data).items():
            row = dict(value or {})
            weights_env = str(row.get("weights_env") or "").strip()
            endpoint_env = str(row.get("endpoint_env") or "").strip()
            module_name = str(row.get("module") or "").strip()
            enabled = bool(row.get("enabled", True))
            row["weights_path"] = os.getenv(weights_env) if weights_env else row.get("weights_path")
            row["endpoint"] = os.getenv(endpoint_env) if endpoint_env else row.get("endpoint")
            missing_reasons: list[str] = []
            if weights_env and not os.getenv(weights_env):
                missing_reasons.append(f"missing_env:{weights_env}")
            if endpoint_env and not os.getenv(endpoint_env):
                missing_reasons.append(f"missing_env:{endpoint_env}")
            if module_name and importlib.util.find_spec(module_name) is None:
                missing_reasons.append(f"missing_module:{module_name}")
            row["available"] = enabled and (
                not weights_env or bool(os.getenv(weights_env))
            ) and (
                not endpoint_env or bool(os.getenv(endpoint_env))
            ) and (not module_name or importlib.util.find_spec(module_name) is not None)
            if not enabled:
                missing_reasons.append("disabled")
            row["availability_reason"] = "ok" if row["available"] else ",".join(missing_reasons) or "unavailable"
            resolved[key] = row
        return resolved
    return {}
