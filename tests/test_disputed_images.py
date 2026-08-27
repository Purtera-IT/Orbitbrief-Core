"""Disputed image-skips wiring: envelope atoms' value["gate_verdict"]["veto"]
(parser-os pdf_image_vision) -> PMHandoff.disputed_images -> markdown.

A gate_verdict WITH a "veto" key means the trained veto head disputes the
skip (thinks the image is meaningful) — a culprit card. A gate_verdict
without veto is an ordinary receipted skip and must NOT become a card.
"""

import copy
import json

from orbitbrief_core.pm_handoff.builder import _build_disputed_images
from orbitbrief_core.pm_handoff.models import PMHandoff
from orbitbrief_core.pm_handoff.render_markdown import (
    _render_disputed_images,
    render_pm_handoff_markdown,
)


def _marker(region_ref="page3/image7", page=3, veto=True, **verdict_over):
    verdict = {
        "kind": "decorative",
        "via": "vlm_gate",
        "confidence": 0.92,
        "ocr_preview": "IDF-2 rack elevation — 24-port PoE switch, patch panel A",
    }
    verdict.update(verdict_over)
    if veto:
        verdict["veto"] = {"meaningful_prob": 0.87, "model": "pdf_image_veto"}
    return {
        "id": "atm_1",
        "artifact_id": "art_pdf_1",
        "atom_type": "deal_metadata",
        "text": "[Image extracted ...]",
        "locator": {"region_ref": region_ref, "page": page,
                    "extraction": "binary_region_marker_v1"},
        "structured": {"kind": "image_marker", "region_ref": region_ref,
                       "saved_path": "/x/crop.png", "gate_verdict": verdict},
    }


_ENVELOPE = {
    "documents": [
        {"artifact_id": "art_pdf_1", "filename": "site_survey.pdf"},
    ],
    "atoms": [
        _marker(),                    # disputed — the card
        _marker(veto=False),          # receipted skip, no veto — NOT a card
        {"id": "atm_x", "structured": {"kind": "scope_item"}},  # unrelated
    ],
}


def _handoff(**kw) -> PMHandoff:
    return PMHandoff(case_id="c1", status="green", status_label="ok",
                     one_line_summary="s", metrics={}, **kw)


class TestBuilderProjection:
    def test_veto_marker_becomes_card_with_provenance(self):
        out = _build_disputed_images(_ENVELOPE)
        assert out["counts"] == {"disputed": 1}
        (card,) = out["cards"]
        assert card["pdf"] == "site_survey.pdf"     # resolved via documents[]
        assert card["page"] == 3
        assert card["region_ref"] == "page3/image7"
        assert card["kind_ruled"] == "decorative"
        assert card["via"] == "vlm_gate"
        assert card["veto_prob"] == 0.87
        assert "IDF-2 rack elevation" in card["ocr_preview"]

    def test_receipted_skip_without_veto_is_not_a_card(self):
        env = {"documents": [], "atoms": [_marker(veto=False)]}
        assert _build_disputed_images(env) == {}

    def test_old_envelope_without_key_is_empty(self):
        assert _build_disputed_images({}) == {}
        assert _build_disputed_images(None) == {}
        assert _build_disputed_images({"atoms": "junk"}) == {}
        assert _build_disputed_images({"atoms": []}) == {}

    def test_caps_report_uncapped_counts(self):
        env = {"documents": [], "atoms": [_marker() for _ in range(25)]}
        out = _build_disputed_images(env)
        assert len(out["cards"]) == 20             # capped for handoff size
        assert out["counts"]["disputed"] == 25     # the truth stays uncapped

    def test_page_falls_back_to_region_ref_and_missing_pdf_degrades(self):
        atom = _marker()
        del atom["locator"]["page"]
        env = {"atoms": [atom]}                     # no documents[] at all
        (card,) = _build_disputed_images(env)["cards"]
        assert card["page"] == 3                    # parsed from page3/image7
        assert card["pdf"] == "art_pdf_1"           # artifact_id fallback

    def test_tolerates_malformed_fields_without_raising(self):
        atom = _marker()
        atom["structured"]["gate_verdict"]["veto"] = {"meaningful_prob": "0.87"}
        atom["structured"]["gate_verdict"]["ocr_preview"] = "x" * 900
        atom["locator"] = {"page": "not-a-page"}
        atom["structured"]["region_ref"] = None
        junk = [
            None, 42, "atom", [],
            {"structured": None},
            {"structured": {"gate_verdict": "junk"}},
            {"structured": {"gate_verdict": {"veto": "fired"}}},  # non-dict veto
        ]
        env = {"documents": ["junk", None], "atoms": junk + [atom]}
        out = _build_disputed_images(env)
        (card,) = out["cards"]
        assert out["counts"]["disputed"] == 1
        assert card["veto_prob"] == 0.87            # string-dressed prob coerced
        assert len(card["ocr_preview"]) == 160      # trimmed
        assert card["page"] is None                 # unparseable everywhere

    def test_never_mutates_the_envelope(self):
        env = copy.deepcopy(_ENVELOPE)
        _build_disputed_images(env)
        assert env == _ENVELOPE


class TestMarkdownSection:
    def test_absent_renders_nothing(self):
        assert _render_disputed_images(_handoff()) == []
        assert _render_disputed_images(
            _handoff(disputed_images=_build_disputed_images({}))) == []

    def test_cards_render_with_doubt_receipts_and_caveat(self):
        h = _handoff(disputed_images=_build_disputed_images(_ENVELOPE))
        md = "\n".join(_render_disputed_images(h))
        assert "Images we skipped — but doubt" in md
        assert "site_survey.pdf" in md and "page 3" in md
        assert "decorative" in md and "vlm_gate" in md
        assert "87% meaningful" in md
        assert "IDF-2 rack elevation" in md          # the human-readable "why"
        assert "still skipped; confirm to reclaim its content" in md

    def test_cap_overflow_is_disclosed(self):
        env = {"documents": [], "atoms": [_marker() for _ in range(25)]}
        h = _handoff(disputed_images=_build_disputed_images(env))
        md = "\n".join(_render_disputed_images(h))
        assert "5 more disputed skip(s) not shown" in md

    def test_malformed_card_fields_render_without_raising(self):
        h = _handoff(disputed_images={
            "cards": [{"veto_prob": "junk", "page": None}, "not-a-dict", None],
            "counts": {"disputed": "three"},
        })
        md = "\n".join(_render_disputed_images(h))
        assert "probability unavailable" in md

    def test_full_handoff_render_includes_the_section(self):
        h = _handoff(disputed_images=_build_disputed_images(_ENVELOPE))
        md = render_pm_handoff_markdown(h)
        assert "Images we skipped — but doubt" in md

    def test_full_handoff_render_omits_section_when_absent(self):
        assert "Images we skipped" not in render_pm_handoff_markdown(_handoff())

    def test_json_round_trip_via_to_dict(self):
        h = _handoff(disputed_images=_build_disputed_images(_ENVELOPE))
        d = json.loads(json.dumps(h.to_dict()))
        assert d["disputed_images"]["counts"]["disputed"] == 1


class TestPortedFromSkipCulpritGenerator:
    """Behaviour ported from the retired PR #66/#67 question-generator
    implementation (question_generators.candidates_from_skipped_image_culprits),
    now folded into _build_disputed_images."""

    def test_value_payload_shape_accepted(self):
        # Older / test envelope shapes stamp the marker on value, not
        # structured (PR #67's dual-read, mirrored here).
        atom = _marker()
        atom["value"] = atom.pop("structured")
        env = {"documents": [], "atoms": [atom]}
        out = _build_disputed_images(env)
        assert out["counts"] == {"disputed": 1}
        assert out["cards"][0]["region_ref"] == "page3/image7"

    def test_scope_hint_extracted_from_ocr(self):
        atom = _marker(ocr_preview="18 Total Data Outlets Comm Cabinet")
        env = {"documents": [], "atoms": [atom]}
        (card,) = _build_disputed_images(env)["cards"]
        assert card["scope_hint"]  # quantity regex hit ("18 ... Outlets")
        assert "18" in card["scope_hint"] or "outlet" in card["scope_hint"].lower()

    def test_scope_hint_falls_back_to_caption_and_can_be_empty(self):
        atom = _marker(ocr_preview="")
        atom["structured"]["expected_content"] = "Rack elevation for IDF closet"
        env = {"documents": [], "atoms": [atom]}
        (card,) = _build_disputed_images(env)["cards"]
        assert card["expected_content"] == "Rack elevation for IDF closet"
        assert card["scope_hint"].lower() == "rack elevation"

        bland = _marker(ocr_preview="Acme Corp")
        bland["structured"].pop("expected_content", None)
        (card2,) = _build_disputed_images({"atoms": [bland]})["cards"]
        assert card2["scope_hint"] == ""

    def test_render_falls_back_to_expected_content_when_ocr_empty(self):
        atom = _marker(ocr_preview="")
        atom["structured"]["expected_content"] = "Floor plan detail"
        h = _handoff(disputed_images=_build_disputed_images({"atoms": [atom]}))
        md = "\n".join(_render_disputed_images(h))
        assert 'Why we doubt the skip: "Floor plan detail"' in md


class TestCropRefs:
    """parser-os (parallel branch) stamps gate_verdict["crop_ref"] — a blob
    path to a saved pixel crop of the disputed image — plus an optional
    "crop_ref_error" liveness receipt when the upload failed, and a
    "veto_soft" soft-band veto that must NEVER become a card (only the hard
    "veto" key makes cards)."""

    CROP = "deals/d1/orbitbrief/disputed_crops/ab12cd34ef56ab78.png"

    def test_crop_ref_passthrough(self):
        atom = _marker(crop_ref=self.CROP)
        (card,) = _build_disputed_images({"atoms": [atom]})["cards"]
        assert card["crop_ref"] == self.CROP
        assert card["crop_ref_error"] == ""

    def test_crop_ref_error_passthrough(self):
        atom = _marker(crop_ref_error="blob PUT 503 after 3 retries")
        (card,) = _build_disputed_images({"atoms": [atom]})["cards"]
        assert card["crop_ref"] == ""
        assert card["crop_ref_error"] == "blob PUT 503 after 3 retries"

    def test_absent_none_and_string_dressed_tolerated(self):
        absent = _marker()                               # keys never stamped
        nones = _marker(crop_ref=None, crop_ref_error=None)
        dressed = _marker(crop_ref=123)                  # string-dressed
        junk = _marker(crop_ref=["deals/x.png"],         # wrong types degrade
                       crop_ref_error={"code": 503})
        env = {"atoms": [absent, nones, dressed, junk]}
        cards = _build_disputed_images(env)["cards"]
        assert [c["crop_ref"] for c in cards] == ["", "", "123", ""]
        assert [c["crop_ref_error"] for c in cards] == ["", "", "", ""]

    def test_markdown_renders_crop_saved_receipt_as_plain_path(self):
        atom = _marker(crop_ref=self.CROP)
        h = _handoff(disputed_images=_build_disputed_images({"atoms": [atom]}))
        md = "\n".join(_render_disputed_images(h))
        assert f"crop saved: `{self.CROP}`" in md
        assert "crop upload failed" not in md
        # Plain path text only — the FE makes the thumbnail; markdown must
        # not fabricate a URL around the blob path.
        assert "http" not in md and "](" not in md

    def test_markdown_renders_error_receipt_when_upload_failed(self):
        atom = _marker(crop_ref_error="blob PUT 503 after 3 retries")
        h = _handoff(disputed_images=_build_disputed_images({"atoms": [atom]}))
        md = "\n".join(_render_disputed_images(h))
        assert "crop upload failed (blob PUT 503 after 3 retries)" in md
        assert "crop saved" not in md

    def test_markdown_omits_both_receipts_when_neither_stamped(self):
        h = _handoff(disputed_images=_build_disputed_images(_ENVELOPE))
        md = "\n".join(_render_disputed_images(h))
        assert "crop saved" not in md
        assert "crop upload failed" not in md

    def test_crop_ref_wins_when_both_present(self):
        atom = _marker(crop_ref=self.CROP, crop_ref_error="late failure")
        h = _handoff(disputed_images=_build_disputed_images({"atoms": [atom]}))
        md = "\n".join(_render_disputed_images(h))
        assert f"crop saved: `{self.CROP}`" in md
        assert "crop upload failed" not in md

    def test_crop_thumb_and_crop_ref_are_independent(self):
        """A crop can be uploaded, thumbnailed, both, or neither."""
        atom = _marker(crop_ref=self.CROP, crop_thumb=TestCropThumbs.THUMB)
        (card,) = _build_disputed_images({"atoms": [atom]})["cards"]
        assert card["crop_ref"] == self.CROP
        assert card["crop_thumb"] == TestCropThumbs.THUMB

    def test_veto_soft_only_is_never_a_card(self):
        soft = _marker(veto=False)
        soft["structured"]["gate_verdict"]["veto_soft"] = {
            "meaningful_prob": 0.55, "model": "pdf_image_veto"
        }
        assert _build_disputed_images({"atoms": [soft]}) == {}

    def test_veto_soft_does_not_leak_into_mixed_envelopes(self):
        soft = _marker(veto=False)
        soft["structured"]["gate_verdict"]["veto_soft"] = {
            "meaningful_prob": 0.55
        }
        hard = _marker(crop_ref=self.CROP)
        out = _build_disputed_images({"atoms": [soft, hard]})
        assert out["counts"] == {"disputed": 1}       # soft not even counted
        (card,) = out["cards"]
        assert card["crop_ref"] == self.CROP


class TestCropThumbs:
    """parser-os also stamps gate_verdict["crop_thumb"] — a small inline JPEG
    data URI of the same crop (<=24KB, hard vetoes only) — plus a
    "crop_thumb_error" receipt when generation failed.

    The thumbnail is for the JSON/UI surface. It is an untrusted blob headed
    for a rendered document, so the builder validates its shape before letting
    it through, and markdown never inlines the base64.
    """

    CROP = "deals/d1/orbitbrief/disputed_crops/ab12cd34ef56ab78.png"
    THUMB = "data:image/jpeg;base64," + "R0lGODlhAQABAIAAAAAAAP" * 4

    def test_valid_data_uri_is_carried(self):
        atom = _marker(crop_thumb=self.THUMB)
        (card,) = _build_disputed_images({"atoms": [atom]})["cards"]
        assert card["crop_thumb"] == self.THUMB
        assert card["crop_thumb_error"] == ""

    def test_png_and_webp_data_uris_also_accepted(self):
        for uri in ("data:image/png;base64,iVBORw0KGgo=",
                    "data:image/webp;base64,UklGRg=="):
            atom = _marker(crop_thumb=uri)
            (card,) = _build_disputed_images({"atoms": [atom]})["cards"]
            assert card["crop_thumb"] == uri

    def test_non_data_uri_junk_is_rejected_to_empty(self):
        """Anything that is not an image data URI never reaches a card —
        including URLs, script payloads, and other data: scheme types."""
        junk = [
            "https://evil.example/x.png",
            "javascript:alert(1)",
            "data:text/html;base64,PHNjcmlwdD4=",   # wrong media type
            "<img src=x onerror=alert(1)>",
            " data:image/jpeg;base64,AAAA",          # leading space, not a URI
            "deals/d1/orbitbrief/disputed_crops/ab12.png",
            "",
        ]
        env = {"atoms": [_marker(crop_thumb=j) for j in junk]}
        cards = _build_disputed_images(env)["cards"]
        assert [c["crop_thumb"] for c in cards] == [""] * len(junk)

    def test_wrong_types_degrade_to_empty(self):
        absent = _marker()                                  # never stamped
        nones = _marker(crop_thumb=None, crop_thumb_error=None)
        numeric = _marker(crop_thumb=123)                   # str only
        listed = _marker(crop_thumb=["data:image/jpeg;base64,AAAA"])
        dicted = _marker(crop_thumb={"uri": "data:image/jpeg;base64,AAAA"})
        env = {"atoms": [absent, nones, numeric, listed, dicted]}
        cards = _build_disputed_images(env)["cards"]
        assert [c["crop_thumb"] for c in cards] == [""] * 5
        assert [c["crop_thumb_error"] for c in cards] == [""] * 5

    def test_oversized_thumb_is_rejected_to_empty(self):
        fat = "data:image/jpeg;base64," + "A" * 60_000
        (card,) = _build_disputed_images(
            {"atoms": [_marker(crop_thumb=fat)]}
        )["cards"]
        assert card["crop_thumb"] == ""

    def test_thumb_at_the_cap_still_passes(self):
        prefix = "data:image/jpeg;base64,"
        ok = prefix + "A" * (40_000 - len(prefix))
        (card,) = _build_disputed_images(
            {"atoms": [_marker(crop_thumb=ok)]}
        )["cards"]
        assert card["crop_thumb"] == ok

    def test_crop_thumb_error_is_carried(self):
        atom = _marker(crop_thumb_error="pillow: cannot open truncated JPEG")
        (card,) = _build_disputed_images({"atoms": [atom]})["cards"]
        assert card["crop_thumb"] == ""
        assert card["crop_thumb_error"] == "pillow: cannot open truncated JPEG"

    def test_crop_thumb_error_is_clamped(self):
        atom = _marker(crop_thumb_error="x" * 500)
        (card,) = _build_disputed_images({"atoms": [atom]})["cards"]
        assert len(card["crop_thumb_error"]) == 160

    def test_markdown_notes_the_thumbnail_without_inlining_base64(self):
        atom = _marker(crop_ref=self.CROP, crop_thumb=self.THUMB)
        h = _handoff(disputed_images=_build_disputed_images({"atoms": [atom]}))
        md = "\n".join(_render_disputed_images(h))
        assert "· thumbnail attached" in md
        # The path receipt is untouched, and the payload never lands in prose.
        assert f"crop saved: `{self.CROP}`" in md
        assert "data:image" not in md
        assert "base64" not in md

    def test_full_markdown_document_never_contains_base64(self):
        atom = _marker(crop_ref=self.CROP, crop_thumb=self.THUMB)
        h = _handoff(disputed_images=_build_disputed_images({"atoms": [atom]}))
        md = render_pm_handoff_markdown(h)
        assert "thumbnail attached" in md
        assert "data:image" not in md
        assert "base64" not in md

    def test_markdown_omits_the_note_when_thumb_absent_or_rejected(self):
        for atom in (_marker(crop_ref=self.CROP),
                     _marker(crop_thumb="https://evil.example/x.png"),
                     _marker(crop_thumb_error="pillow blew up")):
            h = _handoff(
                disputed_images=_build_disputed_images({"atoms": [atom]})
            )
            md = "\n".join(_render_disputed_images(h))
            assert "thumbnail attached" not in md

    def test_thumb_survives_json_round_trip(self):
        atom = _marker(crop_thumb=self.THUMB)
        out = _build_disputed_images({"atoms": [atom]})
        (card,) = json.loads(json.dumps(out))["cards"]
        assert card["crop_thumb"] == self.THUMB

    def test_builder_does_not_mutate_the_envelope(self):
        env = {"atoms": [_marker(crop_thumb=self.THUMB)]}
        before = copy.deepcopy(env)
        _build_disputed_images(env)
        assert env == before
