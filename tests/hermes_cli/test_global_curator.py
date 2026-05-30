"""Tests for the single-consumer global curator (the ordered drain).

Tenants publish lesson proposals to the dedupe topic; the curator drains them serially
and applies merge/corroboration/quorum. This is the architectural fix for the
concurrent-promotion race: one writer to the global pool, fed by an idempotent bus.
"""

from __future__ import annotations

from hermes_state import SessionDB
from hermes_cli.global_memory import list_global_lessons, lesson_corroboration_count
from hermes_cli.global_curator import (
    publish_global_lesson_proposal,
    resolve_dedupe_topic,
    run_global_curator_loop,
    run_global_curator_once,
)
from hermes_cli.learning_bus import list_learning_events


def _lesson(text, *, tenant, evidence, confidence=0.8, held_out=False):
    prov = {"verification": {"held_out": True, "evidence_sha256": "sha-" + tenant}} if held_out else {}
    return {
        "tenant_id": tenant, "repo_id": "r", "approval_state": "approved",
        "scope": "global", "sensitivity": "internal", "visibility": "global_candidate",
        "claim_type": "lesson", "normalized_text": text, "confidence": confidence,
        "evidence_refs": evidence, "cross_tenant_shareable": True, "approval_provenance": prov,
    }


def test_proposals_are_not_written_until_curator_runs(tmp_path):
    """Producer publishes to the bus; the global pool stays empty until the consumer drains."""
    db = SessionDB(tmp_path / "s.db")
    try:
        publish_global_lesson_proposal(db, _lesson("use connection pooling", tenant="A", evidence=["a"]))
        assert list_global_lessons(db, limit=50) == []  # nothing written directly

        res = run_global_curator_once(db)
        assert res.processed == 1 and res.created == 1
        assert len(list_global_lessons(db, limit=50)) == 1
    finally:
        db.close()


def test_idempotent_publish_collapses_redelivery(tmp_path):
    db = SessionDB(tmp_path / "s.db")
    try:
        lesson = _lesson("retry on 503 with jitter", tenant="A", evidence=["a"])
        publish_global_lesson_proposal(db, lesson)
        publish_global_lesson_proposal(db, lesson)  # same tenant+text+evidence → same event_key
        topic = resolve_dedupe_topic(None)
        queued = list_learning_events(db, topic=topic, status="queued")
        assert len(queued) == 1  # collapsed, not two events
    finally:
        db.close()


def test_curator_merges_cross_tenant_rediscovery_serially(tmp_path):
    """Two tenants publish the same lesson; the single consumer merges them into one row."""
    db = SessionDB(tmp_path / "s.db")
    try:
        text = "pin the driver version before running the migration"
        publish_global_lesson_proposal(db, _lesson(text, tenant="A", evidence=["a"]))
        publish_global_lesson_proposal(db, _lesson(text, tenant="B", evidence=["b"], held_out=True))

        res = run_global_curator_loop(db, min_distinct_tenants=2)
        assert res.processed == 2
        assert res.created == 1 and res.merged == 1

        lessons = list_global_lessons(db, limit=50)
        assert len(lessons) == 1  # one canonical row, not two
        assert lesson_corroboration_count(lessons[0]) == 2
        # the merged lesson met quorum (2 distinct tenants) on the run
        assert res.quorum_met >= 1
    finally:
        db.close()


def test_acked_events_are_not_reprocessed(tmp_path):
    db = SessionDB(tmp_path / "s.db")
    try:
        publish_global_lesson_proposal(db, _lesson("x", tenant="A", evidence=["a"]))
        first = run_global_curator_once(db)
        assert first.processed == 1
        second = run_global_curator_once(db)
        assert second.processed == 0  # already consumed, not redelivered
    finally:
        db.close()


def test_loop_drains_until_empty(tmp_path):
    db = SessionDB(tmp_path / "s.db")
    try:
        topics = [
            "pin postgres driver before migration",
            "retry network calls with exponential backoff",
            "rotate credentials through key vault references",
            "use copy for bulk seed loads not insert",
            "set statement timeout before mass updates",
        ]
        for i, text in enumerate(topics):
            publish_global_lesson_proposal(db, _lesson(text, tenant=f"T{i}", evidence=[f"e{i}"]))
        res = run_global_curator_loop(db, limit=2)  # small batch → multiple iterations
        assert res.processed == 5
        assert res.created == 5
        assert len(list_global_lessons(db, limit=50)) == 5
    finally:
        db.close()
