"""Signed-corroboration quorum: a forged/unsigned corroboration cannot count toward
quorum when require_signed is on. Exercised through the real promote→curator path."""

from __future__ import annotations

import pytest

from hermes_state import SessionDB
from hermes_cli.global_curator import (
    promote_candidate_to_global_pool,
    run_global_curator_loop,
)
from hermes_cli.global_memory import (
    list_global_lessons,
    lesson_signed_corroboration_count,
    lesson_meets_quorum,
    merge_or_persist_global_lesson,
)
from hermes_cli.provenance_signing import ProvenanceSigner


SIGNING_CONFIG = {"supervisor": {"provenance_signing": {"strict": True}}}


@pytest.fixture
def signing_key(monkeypatch):
    monkeypatch.setenv("HERMES_PROVENANCE_SIGNING_KEY", "unit-test-signing-key")


def _seed(db, cid, *, tenant, claim):
    verification = {
        "status": "passed", "passed": True, "held_out": True,
        "evidence_uri": f"verification://{tenant}/{cid}", "evidence_sha256": "sha-" + cid,
    }
    db.upsert_meta_candidate(
        candidate_id=cid, kind="runtime_lesson", claim=claim,
        tenant_id=tenant, repo_id="r", status="approved", score=0.9,
        evidence_json={"verification": verification, "evidence_uri": f"ev://{cid}"},
    )


def test_signed_corroborations_are_verified_and_count(signing_key, tmp_path):
    db = SessionDB(tmp_path / "s.db")
    try:
        claim = "pin the driver version before running the migration step"
        _seed(db, "c-A", tenant="A", claim=claim)
        _seed(db, "c-B", tenant="B", claim=claim)
        promote_candidate_to_global_pool(db, candidate_id="c-A", config=SIGNING_CONFIG)
        promote_candidate_to_global_pool(db, candidate_id="c-B", config=SIGNING_CONFIG)

        run = run_global_curator_loop(
            db, config=SIGNING_CONFIG, min_distinct_tenants=2,
            require_held_out=True, require_signed=True,
        )
        assert run.promoted == 1  # both corroborations verified → quorum met → promoted
        lesson = list_global_lessons(db, limit=50)[0]
        assert lesson_signed_corroboration_count(lesson) == 2
        assert lesson["approval_state"] == "canonical"
    finally:
        db.close()


def test_forged_corroboration_does_not_count_under_require_signed(signing_key, tmp_path):
    """A second 'tenant' whose corroboration is unsigned/forged must not satisfy quorum."""
    db = SessionDB(tmp_path / "s.db")
    try:
        claim = "rotate credentials through key vault references only"
        # tenant A promotes legitimately (signed)
        _seed(db, "c-A", tenant="A", claim=claim)
        promote_candidate_to_global_pool(db, candidate_id="c-A", config=SIGNING_CONFIG)
        run_global_curator_loop(db, config=SIGNING_CONFIG, min_distinct_tenants=2,
                                require_held_out=True, require_signed=True)

        # forged: a raw proposal for tenant B with NO valid signature, merged directly
        signer = ProvenanceSigner.from_config(SIGNING_CONFIG)
        forged = {
            "tenant_id": "B", "repo_id": "r", "approval_state": "quarantined",
            "scope": "global", "sensitivity": "internal", "visibility": "global_candidate",
            "claim_type": "lesson", "normalized_text": claim, "confidence": 0.9,
            "evidence_refs": ["ev://forged"], "cross_tenant_shareable": True,
            "approval_provenance": {"signature": "forged-not-valid",
                                    "verification": {"held_out": True, "evidence_sha256": "x"}},
        }
        merge_or_persist_global_lesson(db, forged, signer=signer)

        lesson = list_global_lessons(db, limit=50)[0]
        # two distinct tenants present, but only ONE has a verified signature
        assert lesson_signed_corroboration_count(lesson) == 1
        assert lesson_meets_quorum(lesson, min_distinct_tenants=2, require_signed=True) is False
        # without the signed requirement it would have counted (the gap we closed)
        assert lesson_meets_quorum(lesson, min_distinct_tenants=2, require_signed=False) is True
        # and it stays quarantined (never promoted on forged corroboration)
        assert lesson["approval_state"] == "quarantined"
    finally:
        db.close()


def test_advisory_mode_does_not_break_unsigned_flow(tmp_path):
    """With no signing key (advisory), the existing unsigned quorum path still works."""
    db = SessionDB(tmp_path / "s.db")
    try:
        claim = "set statement timeout before bulk updates"
        _seed(db, "c-A", tenant="A", claim=claim)
        _seed(db, "c-B", tenant="B", claim=claim)
        promote_candidate_to_global_pool(db, candidate_id="c-A")
        promote_candidate_to_global_pool(db, candidate_id="c-B")
        run = run_global_curator_loop(db, min_distinct_tenants=2, require_held_out=True)
        assert run.promoted == 1  # unsigned advisory path unaffected
    finally:
        db.close()
