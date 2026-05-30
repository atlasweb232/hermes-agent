"""Tests for the provenance signing primitive + signed-corroboration quorum."""

from __future__ import annotations

from hermes_cli.provenance_signing import (
    ProvenanceSigner,
    canonical_bytes,
    sign_payload,
    verify_payload,
)


def test_sign_verify_roundtrip():
    key = b"test-key-0123456789"
    payload = {"tenant_id": "A", "evidence_hash": "h", "held_out": True}
    sig = sign_payload(payload, key=key)
    assert verify_payload(payload, sig, key=key) is True


def test_signature_excludes_volatile_fields():
    key = b"k"
    a = {"tenant_id": "A", "evidence_hash": "h", "at": 1.0, "signature": "x", "verified": True}
    b = {"tenant_id": "A", "evidence_hash": "h", "at": 999.0}
    # at/signature/verified are excluded → same signed content → same signature
    assert sign_payload(a, key=key) == sign_payload(b, key=key)


def test_tamper_detection():
    key = b"k"
    payload = {"tenant_id": "A", "evidence_hash": "h"}
    sig = sign_payload(payload, key=key)
    tampered = {"tenant_id": "B", "evidence_hash": "h"}  # tenant swapped
    assert verify_payload(tampered, sig, key=key) is False


def test_wrong_key_fails():
    payload = {"tenant_id": "A"}
    sig = sign_payload(payload, key=b"key1")
    assert verify_payload(payload, sig, key=b"key2") is False


def test_empty_signature_fails():
    assert verify_payload({"x": 1}, "", key=b"k") is False
    assert verify_payload({"x": 1}, None, key=b"k") is False


# ── signer abstraction (config + advisory/strict posture) ───────────────────

def test_signer_disabled_advisory_accepts_unsigned():
    signer = ProvenanceSigner(key=None, strict=False)
    assert signer.enabled is False
    assert signer.sign({"x": 1}) is None
    assert signer.verify({"x": 1}, None) is True  # advisory: accept what it can't check


def test_signer_disabled_strict_rejects():
    signer = ProvenanceSigner(key=None, strict=True)
    assert signer.verify({"x": 1}, "anything") is False


def test_signer_from_config_env_key(monkeypatch):
    monkeypatch.setenv("HERMES_PROVENANCE_SIGNING_KEY", "env-secret-key")
    signer = ProvenanceSigner.from_config({})
    assert signer.enabled is True
    payload = {"tenant_id": "A"}
    assert signer.verify(payload, signer.sign(payload)) is True


def test_signer_enabled_rejects_bad_signature(monkeypatch):
    monkeypatch.setenv("HERMES_PROVENANCE_SIGNING_KEY", "env-secret-key")
    signer = ProvenanceSigner.from_config({})
    assert signer.verify({"tenant_id": "A"}, "deadbeef") is False
