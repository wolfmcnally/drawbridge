from __future__ import annotations

import pytest

from drawbridge.errors import MediaTypeError
import importlib

from drawbridge.identify import identify, sniff_media_type

# The package re-exports identify() under the submodule's name, so fetch the module itself.
identify_module = importlib.import_module("drawbridge.identify")
from drawbridge.pdf_tools import DegeneratePdfError, EncryptedPdfError, MalformedPdfError


def test_native_fixture_is_processable(fixtures):
    result = identify(fixtures / "rfc8785.pdf")
    assert result.outcome == "processable" and result.media_type == "application/pdf"
    assert result.inspection.page_count == 20
    result.raise_for_outcome()  # no-op


def test_invalid_fixture_fails_as_malformed(fixtures):
    result = identify(fixtures / "invalid.pdf")
    assert (result.outcome, result.code) == ("failed", "malformed-pdf")
    with pytest.raises(MalformedPdfError):
        result.raise_for_outcome()


def test_encrypted_is_blocked(encrypted_pdf):
    result = identify(encrypted_pdf)
    assert (result.outcome, result.code, result.blocked_reason) == ("blocked", "password-required", "password-protected")
    with pytest.raises(EncryptedPdfError):
        result.raise_for_outcome()


def test_zero_page_is_blocked(zero_page_pdf):
    result = identify(zero_page_pdf)
    assert (result.outcome, result.code, result.blocked_reason) == ("blocked", "zero-page", "degenerate-input")
    with pytest.raises(DegeneratePdfError):
        result.raise_for_outcome()


def test_non_pdf_is_refused_by_content_not_suffix(tmp_path):
    fake = tmp_path / "notes.pdf"
    fake.write_text("just some text\n")
    result = identify(fake)
    assert result.outcome == "failed" and result.code in {"not-a-pdf", "media-type-unknown"}
    assert result.media_type != "application/pdf"
    with pytest.raises(MediaTypeError):
        result.raise_for_outcome()


def test_pdf_without_suffix_is_still_a_pdf(tmp_path, fixtures):
    unnamed = tmp_path / "attachment"
    unnamed.write_bytes((fixtures / "trivial.pdf").read_bytes())
    assert identify(unnamed).outcome == "processable"


def test_missing_input(tmp_path):
    result = identify(tmp_path / "absent.pdf")
    assert (result.outcome, result.code) == ("failed", "input-missing")


def test_sniff_falls_back_to_magic_bytes(monkeypatch, fixtures):
    monkeypatch.setattr(identify_module.shutil, "which", lambda name: None)
    media, flags = sniff_media_type(fixtures / "trivial.pdf")
    assert media == "application/pdf" and "libmagic-unavailable" in flags


def test_as_dict_round_trips_json(fixtures):
    import json

    data = identify(fixtures / "trivial.pdf").as_dict(include_page_texts=True)
    assert json.loads(json.dumps(data))["inspection"]["page_texts"] == [""]
