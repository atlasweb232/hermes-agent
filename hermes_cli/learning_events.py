"""Learning-plane ingress: a fire-and-forget bus that keeps the self-evolving
loop off the serving path.

Two-plane rule (see docs/architecture/memory-runtime-gap-analysis.md): the serving
plane (the agent doing real work for a tenant) must never pay for the learning plane
(verification capture, held-out grading, corpus build). The delegate hot path does the
*minimum* required for correct serving — run the blocking completion gate — then hands
a ``LearningEvent`` to this bus and returns immediately. Everything expensive
(persisting verification evidence, running held-out checks) happens on a background
daemon thread.

Production-safety properties:

  * **emit never blocks** — the queue is bounded and ``emit`` is non-blocking. Under
    load the bus *sheds* events (drop-newest + counter) rather than back-pressuring the
    serving path. A degraded learning signal is acceptable; a degraded SLO is not.
  * **emit never raises** into the caller — all failures are swallowed/counted.
  * **daemon worker** — never blocks process exit; in-flight events are best-effort.

This is in-process by design (path-1 decouple): same box, separate thread, so latency
leaves the request path without new infra. A fully out-of-box consumer (replaying tasks
against a parked model on separate compute) is the path-2 follow-up; this bus is the
seam it will plug into.
"""

from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_MAX_QUEUE = 256


@dataclass
class LearningEvent:
    """One unit of work for the learning plane, emitted from the delegate hot path."""

    db: Any
    gate: Dict[str, Any]  # completion-gate to_dict() — already computed for blocking
    repo_path: Optional[str]
    task_id: str
    tenant_id: Optional[str] = None
    repo_id: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    candidate_id: Optional[str] = None
    run_held_out: bool = True


def default_learning_handler(event: LearningEvent) -> None:
    """Off-path: persist the visible verification, then run + capture held-out checks.

    Both steps are the things we deliberately moved out of ``run_agent``'s synchronous
    return path. Each is independently guarded so one failure can't sink the other.
    """
    from hermes_cli.verification_evidence import (
        capture_held_out_verification_for_task,
        capture_verification_for_task,
    )

    db = event.db
    if db is None:
        return

    try:
        capture_verification_for_task(
            db,
            event.gate,
            task_id=event.task_id,
            tenant_id=event.tenant_id,
            repo_id=event.repo_id,
            held_out=False,
            candidate_id=event.candidate_id,
        )
    except Exception:
        logger.debug("learning-plane: visible verification capture failed", exc_info=True)

    if event.run_held_out:
        try:
            capture_held_out_verification_for_task(
                db,
                repo_path=event.repo_path,
                task_id=event.task_id,
                tenant_id=event.tenant_id,
                repo_id=event.repo_id,
                candidate_id=event.candidate_id,
                config=event.config,
            )
        except Exception:
            logger.debug("learning-plane: held-out capture failed", exc_info=True)


@dataclass
class _Metrics:
    emitted: int = 0
    processed: int = 0
    dropped: int = 0
    failed: int = 0

    def snapshot(self) -> Dict[str, int]:
        return {
            "emitted": self.emitted,
            "processed": self.processed,
            "dropped": self.dropped,
            "failed": self.failed,
        }


class LearningEventBus:
    """Bounded, fire-and-forget queue with a single daemon consumer."""

    def __init__(
        self,
        handler: Callable[[LearningEvent], None] = default_learning_handler,
        *,
        max_queue: int = DEFAULT_MAX_QUEUE,
    ) -> None:
        self._handler = handler
        self._queue: "queue.Queue[LearningEvent]" = queue.Queue(maxsize=max_queue)
        self._metrics = _Metrics()
        self._lock = threading.Lock()
        self._worker: Optional[threading.Thread] = None
        self._started = False

    def _ensure_worker(self) -> None:
        if self._started:
            return
        with self._lock:
            if self._started:
                return
            self._worker = threading.Thread(
                target=self._run, name="hermes-learning-plane", daemon=True
            )
            self._worker.start()
            self._started = True

    def _run(self) -> None:
        while True:
            event = self._queue.get()
            try:
                self._handler(event)
                with self._lock:
                    self._metrics.processed += 1
            except Exception:
                with self._lock:
                    self._metrics.failed += 1
                logger.debug("learning-plane handler raised", exc_info=True)
            finally:
                self._queue.task_done()

    def emit(self, event: LearningEvent) -> bool:
        """Enqueue without blocking. Returns False if the event was shed (queue full).

        Never raises — the serving path calls this and must not be affected by any
        learning-plane condition.
        """
        try:
            self._ensure_worker()
            self._queue.put_nowait(event)
            with self._lock:
                self._metrics.emitted += 1
            return True
        except queue.Full:
            with self._lock:
                self._metrics.dropped += 1
            return False
        except Exception:
            # Defensive: emit is on the hot path; it must never propagate.
            logger.debug("learning-plane emit failed", exc_info=True)
            return False

    def drain(self, timeout: Optional[float] = None) -> None:
        """Block until the queue is empty. For tests/shutdown — not the hot path."""
        if not self._started:
            return
        if timeout is None:
            self._queue.join()
            return
        # join() has no timeout; emulate with a deadline poll.
        import time

        deadline = time.monotonic() + timeout
        while self._queue.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.01)

    @property
    def metrics(self) -> Dict[str, int]:
        with self._lock:
            return self._metrics.snapshot()


_BUS: Optional[LearningEventBus] = None
_BUS_LOCK = threading.Lock()


def get_learning_bus() -> LearningEventBus:
    global _BUS
    if _BUS is None:
        with _BUS_LOCK:
            if _BUS is None:
                _BUS = LearningEventBus()
    return _BUS


def emit_learning_event(
    *,
    db: Any,
    gate: Dict[str, Any],
    repo_path: Optional[str],
    task_id: str,
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
    candidate_id: Optional[str] = None,
    run_held_out: bool = True,
) -> bool:
    """Convenience: build a LearningEvent and emit it on the process-wide bus.

    Safe to call from the serving path — non-blocking, never raises.
    """
    return get_learning_bus().emit(
        LearningEvent(
            db=db,
            gate=gate,
            repo_path=repo_path,
            task_id=task_id,
            tenant_id=tenant_id,
            repo_id=repo_id,
            config=config,
            candidate_id=candidate_id,
            run_held_out=run_held_out,
        )
    )
