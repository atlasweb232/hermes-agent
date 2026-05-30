"""End-to-end: approved candidate → curator → quorum-gated global lesson.

The poisoning defense made concrete: a candidate is promoted only with passing held-out
verification, enters the global pool QUARANTINED (not usable), and becomes CANONICAL
(usable) only once a second distinct tenant independently corroborates it. One tenant
alone can never make a global lesson live.
"""

from __future__ import annotations

from hermes_state import SessionDB
from hermes_cli.global_curator import (
    promote_candidate_to_global_pool,
    run_global_curator_loop,
)
from hermes_cli.global_memory import list_global_lessons


def _seed_candidate(db, candidate_id, *, tenant, claim, held_out=True, status="approved"):
    verification = {
        "status": "passed", "passed": True, "held_out": held_out,
        "evidence_uri": f"verification://{tenant}/{candidate_id}",
        "evidence_sha256": "sha-" + candidate_id, "summary": "passed",
    }
    db.upsert_meta_candidate(
        candidate_id=candidate_id, kind="runtime_lesson", claim=claim,
        tenant_id=tenant, repo_id="r", status=status, score=0.9,
        evidence_json={"verification": verification, "evidence_uri": f"ev://{candidate_id}"},
    )


def _usable(lessons):
    return [l for l in lessons if str(l.get("approval_state")).lower() in {"approved", "canonical", "applied"}]


def test_unverified_candidate_is_blocked_from_global(tmp_path):
    db = SessionDB(tmp_path / "s.db")
    try:
        db.upsert_meta_candidate(
            candidate_id="c-noverify", kind="runtime_lesson", claim="x",
            tenant_id="A", repo_id="r", status="approved", score=0.9,
            evidence_json={},  # no verification block
        )
        res = promote_candidate_to_global_pool(db, candidate_id="c-noverify")
        assert res.status == "blocked"
        assert "verification" in res.notes.lower()
    finally:
        db.close()


def test_non_held_out_candidate_blocked_when_global_requires_held_out(tmp_path):
    db = SessionDB(tmp_path / "s.db")
    try:
        _seed_candidate(db, "c-visible", tenant="A", claim="pin driver before migrate", held_out=False)
        # default require_held_out_for_global=True → visible-only verification is not enough
        res = promote_candidate_to_global_pool(db, candidate_id="c-visible")
        assert res.status == "blocked"
    finally:
        db.close()


def test_single_tenant_promotion_stays_quarantined_and_unusable(tmp_path):
    db = SessionDB(tmp_path / "s.db")
    try:
        _seed_candidate(db, "c-A", tenant="A", claim="pin the driver version before migration")
        res = promote_candidate_to_global_pool(db, candidate_id="c-A")
        assert res.status == "published"

        run = run_global_curator_loop(db, min_distinct_tenants=2, require_held_out=True)
        assert run.created == 1 and run.promoted == 0  # quorum NOT met → not promoted

        lessons = list_global_lessons(db, limit=50)
        assert len(lessons) == 1
        assert lessons[0]["approval_state"] == "quarantined"
        assert _usable(lessons) == []  # one tenant alone: not usable
    finally:
        db.close()


def test_two_tenant_corroboration_promotes_to_canonical_usable(tmp_path):
    db = SessionDB(tmp_path / "s.db")
    try:
        claim = "pin the driver version before running the migration step"
        _seed_candidate(db, "c-A", tenant="A", claim=claim)
        _seed_candidate(db, "c-B", tenant="B", claim=claim)
        assert promote_candidate_to_global_pool(db, candidate_id="c-A").status == "published"
        assert promote_candidate_to_global_pool(db, candidate_id="c-B").status == "published"

        run = run_global_curator_loop(db, min_distinct_tenants=2, require_held_out=True)
        assert run.created == 1 and run.merged == 1
        assert run.promoted == 1  # quorum met → flipped to canonical

        lessons = list_global_lessons(db, limit=50)
        assert len(lessons) == 1  # one canonical row
        assert lessons[0]["approval_state"] == "canonical"
        assert len(_usable(lessons)) == 1  # now usable
    finally:
        db.close()


def test_unapproved_candidate_cannot_be_promoted(tmp_path):
    db = SessionDB(tmp_path / "s.db")
    try:
        _seed_candidate(db, "c-prop", tenant="A", claim="x", status="proposed")
        res = promote_candidate_to_global_pool(db, candidate_id="c-prop")
        assert res.status == "blocked"
        assert "not approved" in res.notes.lower()
    finally:
        db.close()
