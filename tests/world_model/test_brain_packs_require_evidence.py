"""A pack that can spend 90 seconds of LLM time must first prove it belongs.

``required_anchor_regex_any`` is the burden of proof. Before this test, nine
packs carried it — and they were the *specific* ones (wireless, audio_visual,
low_voltage_cabling, security_camera, electrical). The thirteen vaguest packs
carried none, so they were the only ones that could never be wrong.

Measured on 31 deals with DeepSeek gold labels and real cached envelopes, that
asymmetry produced 78 brain runs of which 58 were on packs the gold label says
are not the deal's work. ``msp`` ran on Clayton — 1,770 atoms — containing not
one of its seven trigger words, while the trained service-router head's correct
pick (``wireless``) was stripped for having one anchor hit instead of two.
"""
from __future__ import annotations

import re

import pytest
import yaml

from orbitbrief_core.world_model.pack_prior.router import PackPrior

PACKS_YAML = "src/orbitbrief_core/world_model/data/domain_packs.yaml"


def _packs() -> dict:
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    raw = yaml.safe_load((root / PACKS_YAML).read_text(encoding="utf-8"))
    entries = raw if isinstance(raw, list) else raw.get("packs") or []
    return {e.get("id") or e.get("pack_id"): e for e in entries if isinstance(e, dict)}


def _brain_capable(pack: dict) -> bool:
    brain = pack.get("brain")
    return isinstance(brain, dict) and brain.get("intent") == "implemented"


def test_every_brain_capable_pack_carries_an_evidence_gate():
    """The invariant. A pack that cannot run a brain may stay ungated; one that
    can must declare what evidence proves it belongs to a deal."""
    ungated = sorted(
        pid for pid, p in _packs().items()
        if _brain_capable(p) and not (p.get("required_anchor_regex_any") or ())
    )
    assert ungated == [], (
        "these packs can burn an LLM brain on zero evidence: " + ", ".join(ungated)
    )


def test_a_facility_name_is_not_datacenter_work():
    """The case the router labeller was written for: a TV install for a customer
    called "Data Center Warehouse" ran the datacenter brain.

    The words alone must not clear the gate — only physical datacenter work
    does. This is also why the gate needs two DISTINCT hits: "data center" and
    "datacenter" are one concept spelled two ways, and would otherwise satisfy
    a two-hit rule by themselves.
    """
    pack = _packs()["datacenter"]
    text = (
        "Statement of work for Data Center Warehouse. Deliver and mount "
        "displays in the datacenter warehouse breakroom. Data Center "
        "Warehouse will provide access."
    )
    distinct = set()
    for pattern in pack["required_anchor_regex_any"]:
        for m in re.finditer(pattern, text, re.I):
            distinct.add(m.group(0).lower())
    need = int(pack.get("required_anchor_min_distinct_hits", 2) or 2)
    assert len(distinct) < need, f"name alone cleared the gate via {distinct}"


def test_real_datacenter_work_still_clears_the_gate():
    """The gate must not be a wall — a genuine datacenter job still passes."""
    pack = _packs()["datacenter"]
    text = (
        "Install 12 cabinets in the hot aisle containment row. Provide rack "
        "elevation drawings and dual PDU feeds per cabinet."
    )
    distinct = set()
    for pattern in pack["required_anchor_regex_any"]:
        for m in re.finditer(pattern, text, re.I):
            distinct.add(m.group(0).lower())
    need = int(pack.get("required_anchor_min_distinct_hits", 2) or 2)
    assert len(distinct) >= need, f"real datacenter work was blocked; hits={distinct}"


@pytest.mark.parametrize("pid", sorted(_packs()))
def test_every_anchor_pattern_compiles(pid):
    """A malformed pattern is silently skipped by the router, which would
    quietly re-open the gate it was meant to close."""
    for pattern in (_packs()[pid].get("required_anchor_regex_any") or ()):
        re.compile(pattern, re.I)


def test_the_registry_actually_loads_the_gates():
    """The YAML is only half of it — DomainPack must surface the anchors, or
    the router reads an empty tuple and lets everything through."""
    pp = PackPrior.with_default_registry()
    for pid, p in _packs().items():
        if not _brain_capable(p):
            continue
        loaded = getattr(pp.registry.get(pid), "required_anchor_regex_any", ()) or ()
        assert loaded, f"{pid}: gate declared in YAML but not loaded by the registry"
