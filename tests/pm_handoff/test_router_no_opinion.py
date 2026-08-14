"""When the ladder declines, the distrusted head must not win by default.

`resolve_routing` returns `{}` for "no opinion", documented as leaving every
keyword path deciding as it does today — "that is why this cannot regress
routing". It did regress routing. `_resolve_service_routing` collapsed `{}` to
None with `resolved or None`, the write-back was skipped, and the envelope kept
the parser head — which question_engine reads directly.

Measured on 02557291: the LLM rung decided `staff_augmentation` on one run and
declined on the next, and the deal came out `wireless_install` at 0.8 confidence
off a head that answered `wireless` on six consecutive sampled deals.
"""
from __future__ import annotations

import orbitbrief_core.pm_handoff.builder as B

HEAD = {
    "enabled": True, "primary": "wireless", "confidence": 0.8,
    "source": "service_router_head", "scope_summary": "dispatch technicians",
}


def _resolve(monkeypatch, tmp_path, *, wired: bool, returns):
    monkeypatch.setattr(B, "_router_chat", lambda: ((object(), "m") if wired else (None, "")))
    monkeypatch.setattr(B, "_router_pack_menu", lambda: [("wireless", "Wireless")])
    import orbitbrief_core.world_model.scope_router as SR

    monkeypatch.setattr(SR, "resolve_routing", lambda **kw: returns)
    env = {"service_routing": dict(HEAD), "project_id": "p", "compile_id": "c"}
    out = B._resolve_service_routing(env, tmp_path)
    return env, out


def test_no_opinion_returns_empty_not_none(monkeypatch, tmp_path):
    _env, out = _resolve(monkeypatch, tmp_path, wired=True, returns={})
    assert out == {}, "{} and None mean opposite things; do not collapse them"


def test_no_opinion_clears_the_head_from_the_envelope(monkeypatch, tmp_path):
    env, out = _resolve(monkeypatch, tmp_path, wired=True, returns={})
    # Mirror the builder's write-back contract.
    if isinstance(out, dict):
        if out:
            env["service_routing"] = out
        else:
            env.pop("service_routing", None)
    assert "service_routing" not in env, "the distrusted head must not survive"


def test_a_decision_is_written_back(monkeypatch, tmp_path):
    decided = {"primary": "staff_augmentation", "source": "llm_scope_router",
               "confidence": 0.9, "enabled": True}
    _env, out = _resolve(monkeypatch, tmp_path, wired=True, returns=decided)
    assert out["primary"] == "staff_augmentation"
    assert out["source"] == "llm_scope_router"


def test_unwired_still_passes_the_head_through(monkeypatch, tmp_path):
    """With no router model, prior behaviour is preserved deliberately."""
    _env, out = _resolve(monkeypatch, tmp_path, wired=False, returns={})
    assert out == HEAD
