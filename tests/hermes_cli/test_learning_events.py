"""Tests for the learning-plane bus (two-plane decouple).

Covers the production-safety contract: emit is non-blocking, never raises, sheds load
when the queue is full, and the default handler does the verification + held-out capture
off the serving path.
"""

from __future__ import annotations

import threading
import time

from hermes_cli.learning_events import (
    LearningEvent,
    LearningEventBus,
    default_learning_handler,
    emit_learning_event,
    get_learning_bus,
)


def _passing_gate():
    return {
        "enabled": True,
        "status": "passed",
        "repo_path": "/repo",
        "passed": True,
        "checks": [{"name": "build", "passed": True, "skipped": False, "command": ["true"]}],
    }


# ── the production-safety contract ──────────────────────────────────────────

def test_emit_is_async_and_processes_off_thread():
    seen = []
    done = threading.Event()

    def handler(event):
        seen.append(event.task_id)
        done.set()

    bus = LearningEventBus(handler=handler)
    assert bus.emit(LearningEvent(db=object(), gate={}, repo_path=None, task_id="t1")) is True
    assert done.wait(timeout=2.0)
    bus.drain(timeout=1.0)
    assert seen == ["t1"]
    assert bus.metrics["processed"] == 1


def test_emit_sheds_load_when_queue_full_without_blocking():
    """A slow handler must not back-pressure the producer; excess events are dropped."""
    release = threading.Event()

    def slow_handler(event):
        release.wait(timeout=5.0)  # block the single worker

    bus = LearningEventBus(handler=slow_handler, max_queue=2)
    # First emit is picked up by the worker (blocks there); next 2 fill the queue;
    # everything after is shed. None of these calls may block.
    results = []
    start = time.monotonic()
    for i in range(20):
        results.append(bus.emit(LearningEvent(db=None, gate={}, repo_path=None, task_id=str(i))))
    elapsed = time.monotonic() - start

    assert elapsed < 1.0  # emit never blocked on the slow handler
    assert results.count(False) >= 1  # at least one event was shed
    assert bus.metrics["dropped"] >= 1
    release.set()


def test_emit_never_raises_even_with_broken_handler():
    def broken(event):
        raise RuntimeError("handler boom")

    bus = LearningEventBus(handler=broken)
    assert bus.emit(LearningEvent(db=None, gate={}, repo_path=None, task_id="t")) is True
    bus.drain(timeout=1.0)
    # handler failure is counted, not propagated
    assert bus.metrics["failed"] == 1
    assert bus.metrics["processed"] == 0


def test_default_handler_with_none_db_is_noop():
    default_learning_handler(LearningEvent(db=None, gate=_passing_gate(), repo_path=None, task_id="t"))


# ── the default handler does the real capture off-path ──────────────────────

def test_default_handler_persists_verification(tmp_path):
    from hermes_state import SessionDB
    from hermes_cli.verification_evidence import evidence_has_passing_verification

    db = SessionDB(tmp_path / "state.db")
    try:
        db.upsert_meta_candidate(
            candidate_id="cand-async", kind="runtime_lesson", claim="x",
            tenant_id="A", repo_id="r", status="proposed",
        )
        default_learning_handler(
            LearningEvent(
                db=db, gate=_passing_gate(), repo_path=None, task_id="t",
                tenant_id="A", repo_id="r", candidate_id="cand-async",
                run_held_out=False,
            )
        )
        candidate = db.get_meta_candidate("cand-async")
        assert evidence_has_passing_verification(candidate.get("evidence_json")) is True
    finally:
        db.close()


def test_end_to_end_emit_then_drain_captures(tmp_path):
    from hermes_state import SessionDB
    from hermes_cli.verification_evidence import evidence_has_passing_verification

    db = SessionDB(tmp_path / "state.db")
    try:
        db.upsert_meta_candidate(
            candidate_id="cand-e2e", kind="runtime_lesson", claim="x",
            tenant_id="A", repo_id="r", status="proposed",
        )
        # use a dedicated bus (not the process singleton) for test isolation
        bus = LearningEventBus()
        bus.emit(
            LearningEvent(
                db=db, gate=_passing_gate(), repo_path=None, task_id="t",
                tenant_id="A", repo_id="r", candidate_id="cand-e2e", run_held_out=False,
            )
        )
        bus.drain(timeout=2.0)
        candidate = db.get_meta_candidate("cand-e2e")
        assert evidence_has_passing_verification(candidate.get("evidence_json")) is True
    finally:
        db.close()


def test_get_learning_bus_is_singleton():
    assert get_learning_bus() is get_learning_bus()
