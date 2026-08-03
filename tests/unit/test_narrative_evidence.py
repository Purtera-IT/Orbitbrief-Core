"""No-loss PM narrative RAG pack — facets, dedupe, full atom text."""

from __future__ import annotations

from orbitbrief_core.pm_handoff.narrative_evidence import (
    FACETS,
    build_narrative_rag_pack,
    collect_envelope_atoms,
    facet_coverage_summary,
)


def _atom(
    aid: str,
    text: str,
    *,
    atype: str = "claim",
    conf: float = 0.9,
) -> dict:
    return {
        "atom_id": aid,
        "type": atype,
        "text": text,
        "confidence": conf,
        "sites": [],
        "source_refs": [{"doc_id": "d1"}],
    }


def test_collect_prefers_full_envelope_text() -> None:
    long = (
        "Commercial NTE is $248,500 including freight contingency and "
        "change-order reserve for all Decatur wave-1 sites. "
    ) * 3
    envelope = {
        "atoms": [
            _atom("atm_1", long, atype="money"),
            _atom(
                "atm_2",
                "Access window M-F 06:00-18:00 with escort required.",
                atype="access_requirement",
            ),
        ]
    }
    atoms = collect_envelope_atoms(envelope)
    assert len(atoms) == 2
    assert atoms[0]["text"].strip() == long.strip()
    assert "escort required" in atoms[1]["text"]


def test_rag_pack_covers_all_facets_without_duplicate_text() -> None:
    envelope = {
        "atoms": [
            _atom("a1", "Scope includes AV, network, and access control refresh.", atype="scope_item"),
            _atom("a2", "Commercial NTE is $248,500 fixed fee.", atype="money"),
            _atom("a3", "Primary site is NE Decatur AL warehouse.", atype="physical_site"),
            _atom("a4", "Access requires TWIC and 48h notice.", atype="access_requirement"),
            _atom("a5", "BOM lists Crestron NVX endpoints and Cisco switches.", atype="bom_line"),
            _atom("a6", "Risk: lead time on NVX may slip install.", atype="risk"),
            _atom("a7", "Acceptance requires punch and as-builts.", atype="acceptance"),
            _atom("a8", "Schedule targets Q3 cutover.", atype="schedule_phase"),
            _atom("a9", "PM owner is Jordan Lee; SA is Kim Park.", atype="stakeholder"),
            # Near-duplicate commercial — must not crowd out other facets
            _atom("a10", "Commercial NTE is $248,500 fixed fee.", atype="money"),
        ]
    }
    pack = build_narrative_rag_pack(envelope=envelope, cap=24)
    texts = [r["text"] for r in pack]
    assert len(texts) == len(set(texts))
    coverage = facet_coverage_summary(pack)
    for need in FACETS:
        assert coverage.get(need, 0) >= 1, f"missing facet {need}: {coverage}"


def test_rag_pack_falls_back_to_report_lineage() -> None:
    pack = build_narrative_rag_pack(
        envelope={"atoms": []},
        report={
            "atom_lineage": [
                {
                    "atom_id": "x1",
                    "type": "risk",
                    "text": "Ceiling height conflict at loading dock may block lift path.",
                    "confidence": 0.85,
                }
            ]
        },
        cap=10,
    )
    assert len(pack) >= 1
    assert "loading dock" in pack[0]["text"]


def test_soft_filter_keeps_acceptance_without_deal_lexemes() -> None:
    """Fact-card neural filter would drop these; narrative pack must keep them."""
    pack = build_narrative_rag_pack(
        envelope={
            "atoms": [
                _atom("a7", "Acceptance requires punch and as-builts.", atype="acceptance"),
                _atom("a9", "PM owner is Jordan Lee; SA is Kim Park.", atype="stakeholder"),
            ]
        },
        cap=10,
    )
    facets = {f for r in pack for f in (r.get("facets") or [])}
    assert "acceptance" in facets
    assert "stakeholders" in facets


def test_sanitize_ocr_commercial_and_address() -> None:
    from orbitbrief_core.pm_handoff.narrative_evidence import sanitize_narrative_text

    raw = (
        "BILLING INCREMENT: 3 Sites: Survey & 8 Tank Installs Fixed | "
        "TED FEES SD): ( ) $1,960.00"
    )
    cleaned = sanitize_narrative_text(raw)
    assert "TED FEES" not in cleaned.upper()
    assert "$1,960" in cleaned
    assert "Survey" in cleaned or "Tank" in cleaned
    assert "Fixed commercial line:" in cleaned
    addr = sanitize_narrative_text("1215 S. Jefferson |, Saginaw, MI 48601")
    assert "|," not in addr
    assert "Saginaw" in addr


def test_drops_thin_stakeholder_raw_address_and_ocr_shred() -> None:
    pack = build_narrative_rag_pack(
        envelope={
            "atoms": [
                _atom(
                    "s1",
                    "Megan Blevins | Global Strategic Account Executive",
                    atype="stakeholder",
                ),
                _atom(
                    "s2",
                    "1215 S. Jefferson |, Saginaw, MI 48601",
                    atype="address",
                ),
                _atom(
                    "s3",
                    "The estimated Fees for Services outlined below are Fixed Fee.",
                    atype="money",
                ),
                _atom(
                    "s4",
                    "DESCRIPTION: DESCRIP — col_2: PTION — BILLING INCREMENT — MATED: (USD).",
                    atype="money",
                ),
                _atom(
                    "s5",
                    "BILLING INCREMENT: 3 Sites: Survey & 8 Tank Installs Fixed | "
                    "TED FEES SD): ( ) $1,960.00",
                    atype="money",
                ),
                _atom(
                    "s6",
                    "PurTera will install ANOVA tank monitors at Decatur.",
                    atype="scope_item",
                ),
            ]
        },
        cap=10,
    )
    texts = " ".join(r["text"] for r in pack)
    assert "Megan Blevins" not in texts
    assert "1215" not in texts
    assert "estimated Fees" not in texts
    assert "col_2" not in texts
    assert "TED FEES" not in texts.upper()
    assert "ANOVA" in texts
    assert "$1,960" in texts
