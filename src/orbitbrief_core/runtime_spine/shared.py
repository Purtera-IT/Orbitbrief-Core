from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from itertools import count
from typing import Any

_COUNTER = count(1)


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def make_id(prefix: str) -> str:
    return f"{prefix}_{next(_COUNTER)}"


def stable_value_hash(value: Any) -> str:
    blob = json.dumps(value, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def normalize_whitespace(text: str) -> str:
    return " ".join(text.split())
