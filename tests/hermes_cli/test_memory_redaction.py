"""Tests for the strict memory-persistence redactor.

Persisted/curated memory may be shared cross-tenant, so the contract is
*stronger* than log redaction: zero secret fragments survive (no preserved
prefixes), and ``contains_secret`` is False on every redacted result.
"""

import pytest

from hermes_cli.memory_redaction import (
    REDACTION_PLACEHOLDER,
    contains_secret,
    redact_for_persistence,
)


SECRET_INPUTS = [
    "token=sk-abc123456789XYZ",
    "password=supersecret",
    "api_key: 'AKIAIOSFODNN7EXAMPLE'",
    "client_secret=zzzzzzzzzzzzzzzzzzzzzzzz",
    "bot=123456:ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    'Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.sig',
    "postgres://user:hunter2@db.example.com:5432/app",
    '{"secret": "sk-abc123456789XYZ"}',
]


@pytest.mark.parametrize("text", SECRET_INPUTS)
def test_no_secret_fragment_survives(text):
    out = redact_for_persistence(text)
    # No raw secret substrings leak through (incl. the sk- prefix the log
    # redactor would otherwise preserve as ``sk-abc...``).
    for leak in ("sk-abc", "supersecret", "hunter2", "AKIAIOSFODNN7EXAMPLE"):
        assert leak not in out
    # The strict pass is authoritative: detection finds nothing afterwards.
    assert contains_secret(out) is False


def test_lowercase_password_assignment_is_caught():
    # The canonical log redactor misses this; the strict pass must not.
    out = redact_for_persistence("password=supersecret")
    assert "supersecret" not in out
    assert REDACTION_PLACEHOLDER in out


def test_sk_prefix_fully_erased_not_masked():
    out = redact_for_persistence("token=sk-abc123456789XYZ")
    assert out == REDACTION_PLACEHOLDER  # not "token=sk-abc...9XYZ"


def test_contains_secret_detects_and_clears():
    assert contains_secret("api_key=deadbeefdeadbeef") is True
    assert contains_secret("nothing sensitive here") is False


def test_plain_text_passes_through():
    assert redact_for_persistence("just a normal lesson body") == "just a normal lesson body"


def test_length_bounding_is_separate_and_applied():
    out = redact_for_persistence("x" * 100, max_chars=20)
    assert len(out) <= 20
    assert out.endswith("...")
    # Redaction without bounding leaves length untouched.
    assert redact_for_persistence("x" * 100) == "x" * 100


def test_none_and_empty_safe():
    assert redact_for_persistence(None) == ""
    assert redact_for_persistence("") == ""
    assert contains_secret(None) is False
