"""Verifiable-reward bridge: completion-gate evidence → learning/training path.

This is the teacher-independence primitive. The self-evolving loop is bounded by
its teacher whenever the reward signal is a model's judgment. To let a student
model exceed its teacher in-domain, the promotion/training signal must be grounded
in a model-independent oracle: does the code actually compile, pass tests, satisfy
the spec — i.e. the deterministic completion gate (``hermes_cli/completion_gate``).

This module:
  1. Turns a ``CompletionGateResult`` into a content-addressed ``VerificationRecord``
     (sha256 over the canonical gate dict — tamper-evident; Phase 4 signing hooks
     onto ``signature``).
  2. Persists it as memory evidence and attaches a compact ``verification`` block to
     a learning candidate's ``evidence_json``.
  3. Exposes the predicate the promotion gate uses
     (``evidence_has_passing_verification``) so a candidate cannot be approved /
     globally promoted on an LLM judge's say-so alone.

Reward-hacking note: a worker WILL learn to game the *visible* build commands
(Goodhart). ``held_out=True`` marks a verification produced by checks the worker
never saw (held-out tests + spec-conformance). Global/cross-tenant promotion should
require ``require_held_out=True`` — analogous to a train/test split.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


VERIFICATION_MIME = "application/vnd.hermes.verification+json"
VERIFICATION_EVIDENCE_KEY = "verification"


@dataclass
class VerificationRecord:
    """A model-independent verification outcome for one task."""

    task_id: str
    status: str  # "passed" | "blocked" | "skipped"
    tenant_id: Optional[str] = None
    repo_id: Optional[str] = None
    checks: List[Dict[str, Any]] = field(default_factory=list)
    held_out: bool = False
    evidence_uri: str = ""
    evidence_sha256: str = ""
    summary: str = ""
    created_at: float = 0.0
    # Phase 4 hook: HMAC/asymmetric signature over evidence_sha256. None until then.
    signature: Optional[str] = None

    @property
    def passed(self) -> bool:
        return self.status == "passed"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "tenant_id": self.tenant_id,
            "repo_id": self.repo_id,
            "checks": self.checks,
            "held_out": self.held_out,
            "evidence_uri": self.evidence_uri,
            "evidence_sha256": self.evidence_sha256,
            "summary": self.summary,
            "created_at": self.created_at,
            "signature": self.signature,
        }

    def to_evidence_block(self) -> Dict[str, Any]:
        """Compact block attached to a candidate's evidence_json (no raw stdout)."""
        return {
            "status": self.status,
            "passed": self.passed,
            "held_out": self.held_out,
            "evidence_uri": self.evidence_uri,
            "evidence_sha256": self.evidence_sha256,
            "summary": self.summary,
            "checks": [
                {"name": c.get("name"), "passed": bool(c.get("passed")),
                 "skipped": bool(c.get("skipped"))}
                for c in self.checks
            ],
            "signature": self.signature,
        }


def _canonical_sha256(payload: Dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def verification_record_from_gate(
    gate: Any,
    *,
    task_id: str,
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    held_out: bool = False,
) -> VerificationRecord:
    """Build a content-addressed VerificationRecord from a CompletionGateResult.

    ``gate`` may be a CompletionGateResult or its ``to_dict()`` form.
    """
    gate_dict = gate.to_dict() if hasattr(gate, "to_dict") else dict(gate or {})
    status = str(gate_dict.get("status") or "skipped")
    checks = gate_dict.get("checks") or []
    if not isinstance(checks, list):
        checks = []
    # Hash the full gate dict (incl. command output) — the tamper-evident anchor.
    sha = _canonical_sha256(gate_dict)
    evidence_uri = f"verification://{tenant_id or '_'}/{repo_id or '_'}/{task_id}/{sha[:16]}"
    n_pass = sum(1 for c in checks if isinstance(c, dict) and c.get("passed") and not c.get("skipped"))
    n_fail = sum(1 for c in checks if isinstance(c, dict) and not c.get("passed") and not c.get("skipped"))
    summary = f"{status}: {n_pass} passed, {n_fail} failed" + (" (held-out)" if held_out else "")
    return VerificationRecord(
        task_id=task_id,
        status=status,
        tenant_id=tenant_id,
        repo_id=repo_id,
        checks=[c for c in checks if isinstance(c, dict)],
        held_out=held_out,
        evidence_uri=evidence_uri,
        evidence_sha256=sha,
        summary=summary,
        created_at=time.time(),
    )


def record_verification_evidence(db: Any, record: VerificationRecord) -> int:
    """Persist the verification as a row in hermes_memory_evidence.

    Returns the evidence row id (or -1 on failure). The excerpt is the compact
    summary — raw command output is intentionally NOT stored in the evidence row.
    """
    try:
        return db.add_memory_evidence(
            uri=record.evidence_uri,
            record_id=None,
            packet_id=None,
            sha256=record.evidence_sha256,
            mime_type=VERIFICATION_MIME,
            excerpt=record.summary,
            tenant_id=record.tenant_id,
        )
    except TypeError:
        # SessionDB.add_memory_evidence signature without tenant_id (older path).
        return db.add_memory_evidence(
            uri=record.evidence_uri,
            record_id=None,
            packet_id=None,
            sha256=record.evidence_sha256,
            mime_type=VERIFICATION_MIME,
            excerpt=record.summary,
        )


def attach_verification_to_candidate_evidence(
    evidence: Any, record: VerificationRecord
) -> Dict[str, Any]:
    """Merge the verification block into a candidate's evidence_json dict."""
    merged: Dict[str, Any] = dict(evidence) if isinstance(evidence, dict) else {}
    merged[VERIFICATION_EVIDENCE_KEY] = record.to_evidence_block()
    return merged


def evidence_has_passing_verification(
    evidence: Any, *, require_held_out: bool = False
) -> bool:
    """Predicate the promotion gate uses. Fail-closed: missing/invalid → False.

    A candidate's evidence_json must carry a ``verification`` block whose status is
    ``passed``. When ``require_held_out`` is set (global/cross-tenant promotion), the
    verification must also have been produced by held-out (worker-unseen) checks.
    """
    if not isinstance(evidence, dict):
        return False
    block = evidence.get(VERIFICATION_EVIDENCE_KEY)
    if not isinstance(block, dict):
        return False
    if not bool(block.get("passed")) or str(block.get("status")) != "passed":
        return False
    if require_held_out and not bool(block.get("held_out")):
        return False
    return True


def capture_verification_for_task(
    db: Any,
    gate: Any,
    *,
    task_id: str,
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    held_out: bool = False,
    candidate_id: Optional[str] = None,
) -> VerificationRecord:
    """End-to-end: build record, persist evidence, optionally attach to a candidate.

    Designed to be called from the delegate flow where the gate is already in hand
    (``run_agent`` after ``run_completion_gate``). Best-effort: persistence/attach
    failures don't raise — the returned record is always valid.
    """
    record = verification_record_from_gate(
        gate, task_id=task_id, tenant_id=tenant_id, repo_id=repo_id, held_out=held_out
    )
    try:
        record_verification_evidence(db, record)
    except Exception:
        pass
    if candidate_id:
        try:
            candidate = db.get_meta_candidate(candidate_id)
            if candidate is not None:
                merged = attach_verification_to_candidate_evidence(
                    candidate.get("evidence_json"), record
                )
                db.update_meta_candidate_status(
                    candidate_id,
                    status=str(candidate.get("status") or "proposed"),
                    evidence_json=merged,
                )
        except Exception:
            pass
    return record


def capture_held_out_verification_for_task(
    db: Any,
    *,
    repo_path: Optional[str],
    task_id: str,
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    candidate_id: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Optional[VerificationRecord]:
    """Run the held-out (worker-unseen) gate and capture it as a held-out verification.

    This is what makes ``held_out=True`` *earned* rather than asserted: the flag is set
    only when ``run_held_out_gate`` actually executed configured unseen checks (its
    status is not ``skipped``). When no held-out commands are configured, returns
    ``None`` — there is deliberately no way to mint a held-out verification without
    checks having run.

    Run by the supervisor/curator AFTER the worker reports done — never from the
    delegate flow, or the worker would see the held-out commands.
    """
    try:
        from hermes_cli.completion_gate import run_held_out_gate
    except Exception:
        return None
    gate = run_held_out_gate(repo_path=repo_path, config=config)
    if getattr(gate, "status", "skipped") == "skipped":
        return None  # no held-out checks ran → cannot claim held-out
    return capture_verification_for_task(
        db, gate, task_id=task_id, tenant_id=tenant_id, repo_id=repo_id,
        held_out=True, candidate_id=candidate_id,
    )


def load_verification_gate_config(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Read verification-gate policy from config (safe defaults; no config mutation).

    Defaults preserve the existing advisory posture: enforcement OFF until an
    operator opts in. When enabled, approval requires passing verification evidence,
    and global/cross-tenant promotion additionally requires held-out verification.
    """
    learning = ((config or {}).get("learning") or {})
    gate = learning.get("verification_gate") if isinstance(learning.get("verification_gate"), dict) else {}
    return {
        "require_verification_for_approval": bool(gate.get("require_verification_for_approval", False)),
        "require_held_out_for_global": bool(gate.get("require_held_out_for_global", True)),
    }
