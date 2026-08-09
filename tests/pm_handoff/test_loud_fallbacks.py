"""A degraded brief must announce itself.

Silent degradation is why the overview was missing for weeks: falling back to
the one-line summary reads like a short brief rather than a failure, and no
counter, log line or field recorded that a stage had given up. The same shape
cost a dozen compiles in one evening — `?async=1` answered 202 while the task
died in-process with a bare `except: pass`.

A fallback nobody can observe is not resilience, it is a hidden outage.
"""

import inspect

from orbitbrief_core.pm_handoff.reconciliation import build_executive_summary


def _summary(**kw):
    return build_executive_summary(
        case_id="000043",
        status="red",
        status_label="Not SOW-ready",
        one_line_summary="Wireless install at 3 sites.",
        money_mentions=[],
        risks=[],
        gaps=[],
        sites=[],
        domains=[],
        project_mode="wireless_install",
        **kw,
    )


def test_degraded_overview_says_so(monkeypatch):
    """When the overview builder yields nothing, the panel must not look fine."""
    import orbitbrief_core.pm_handoff.pm_briefing as pb

    monkeypatch.setattr(pb, "build_pm_briefing_overview", lambda **_kw: "")
    ov = _summary().overview
    assert "could not be built" in ov, ov
    # The one-liner is still carried, so the PM is not left with only a warning.
    assert "Wireless install" in ov


def test_builder_crash_is_also_announced(monkeypatch):
    """A raising builder must degrade loudly, not silently."""
    import orbitbrief_core.pm_handoff.pm_briefing as pb

    def _boom(**_kw):
        raise RuntimeError("inference host timed out")

    monkeypatch.setattr(pb, "build_pm_briefing_overview", _boom)
    assert "could not be built" in _summary().overview


def test_healthy_overview_carries_no_notice():
    """The notice must not appear on a brief that built normally."""
    ov = _summary().overview
    assert ov.strip()
    assert "could not be built" not in ov


def test_background_compile_no_longer_swallows_failures():
    """`except: pass` made a dropped compile invisible to everyone."""
    from pathlib import Path

    src = Path(__file__).parents[2] / "orbitbrief-core-worker" / "app.py"
    body = src.read_text(encoding="utf-8")
    fn = body.split("def _background_compile", 1)[1].split("\n@app", 1)[0]
    assert "pass" not in fn.split("except Exception:")[1][:80], "failure still swallowed"
    assert "compile start" in fn and "compile FAILED" in fn
