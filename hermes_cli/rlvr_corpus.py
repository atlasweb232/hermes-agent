"""RLVR (Reinforcement Learning with Verifiable Rewards) corpus schema.

This is the data shape that makes a student model able to exceed its teacher
*in-domain*. The teacher-independence invariant is embedded in the schema itself:
every reward in a rollout group is sourced from the model-independent completion
gate (compile / tests / held-out / spec), never from an LLM judge. A group records
this provenance explicitly (``oracle.reward_source = "model_independent"`,
``oracle.judge_in_reward_loop = False``) so any downstream training job can assert
the property before it trusts the data.

The unit is a **rollout group**: one task, N sampled attempts from the worker
(student) policy, each graded by the verifiable oracle. This single shape supports:

  * **Rejection-sampling SFT** — keep the verified-passing trajectories, train on them.
  * **RLVR / GRPO** — the whole group with group-relative advantages
    (``advantage_i = reward_i - mean(reward)``); no separate value model needed.
  * **Preference pairs (DPO/ORPO)** — pair a verified rollout (chosen) against a
    failing one (rejected).

A worker that overfit the *visible* build commands does not earn a held-out reward
here, so the signal stays honest (see ``hermes_cli.completion_gate.run_held_out_gate``
and ``hermes_cli.verification_evidence``).

Like ``mlops_corpus``, this module stops at deterministic corpus artifacts. It does
not schedule training, write registries, deploy models, or affect runtime routing.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from hermes_state import SessionDB
from hermes_cli.verification_evidence import VerificationRecord


RLVR_ROLLOUT_SCHEMA = "mlops.corpus.rlvr_rollout.v1"
RLVR_GROUP_SCHEMA = "mlops.corpus.rlvr_rollout_group.v1"

# Methods a verified rollout group can legitimately feed. Kept aligned with
# mlops_corpus.ALLOWED_METHODS plus the verifiable-reward RL methods.
RLVR_METHODS = {"sft", "rft", "rejection_sampling", "dpo", "orpo", "grpo", "rlvr"}


def _now() -> float:
    return time.time()


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _json_loads(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not value:
        return {}
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return {}


def _stable_id(prefix: str, *parts: Any) -> str:
    digest = hashlib.sha256(
        "|".join("" if p is None else str(p) for p in parts).encode("utf-8")
    ).hexdigest()
    return f"{prefix}_{digest[:24]}"


def reward_from_verification(block: Optional[Dict[str, Any]]) -> float:
    """Map a verification evidence block to a scalar reward in [0, 1].

    The reward is the *oracle's* verdict, not a model's: 1.0 when the harness passed,
    else 0.0. This binary verifiable reward is exactly the RLVR signal (rule-based,
    no learned reward model). ``checks_passed_fraction`` is kept separately as a soft
    diagnostic — it is NOT the training reward, to avoid rewarding partial credit the
    gate itself does not grant.
    """
    if not isinstance(block, dict):
        return 0.0
    return 1.0 if (bool(block.get("passed")) and str(block.get("status")) == "passed") else 0.0


def _checks_passed_fraction(block: Optional[Dict[str, Any]]) -> float:
    if not isinstance(block, dict):
        return 0.0
    checks = [c for c in (block.get("checks") or []) if isinstance(c, dict) and not c.get("skipped")]
    if not checks:
        return 0.0
    return sum(1 for c in checks if c.get("passed")) / len(checks)


@dataclass
class RLVRRollout:
    """One sampled attempt by the worker (student) policy, graded by the oracle."""

    rollout_id: str
    attempt_index: int
    # Compact, redaction-safe — never the raw transcript. ``trajectory_ref`` points to
    # the durable artifact (evidence uri); ``trajectory_summary`` is a bounded excerpt.
    trajectory_ref: str
    trajectory_summary: str
    verification: Dict[str, Any]  # VerificationRecord.to_evidence_block()
    reward: float = 0.0
    advantage: float = 0.0
    held_out: bool = False
    verified: bool = False
    checks_passed_fraction: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": RLVR_ROLLOUT_SCHEMA,
            "rollout_id": self.rollout_id,
            "attempt_index": self.attempt_index,
            "trajectory_ref": self.trajectory_ref,
            "trajectory_summary": self.trajectory_summary,
            "verification": self.verification,
            "reward": self.reward,
            "advantage": self.advantage,
            "held_out": self.held_out,
            "verified": self.verified,
            "checks_passed_fraction": self.checks_passed_fraction,
        }


@dataclass
class RLVRRolloutGroup:
    """One task + N graded rollouts. The atomic RLVR training example."""

    group_id: str
    task: Dict[str, Any]
    policy: Dict[str, Any]  # which student produced these: {worker_model, worker_version}
    rollouts: List[RLVRRollout] = field(default_factory=list)
    tenant_id: Optional[str] = None
    repo_id: Optional[str] = None
    dataset_family: str = "policy_playbook"
    scope: str = "tenant"
    safety: Dict[str, Any] = field(default_factory=dict)
    approval: Dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0

    # ── derived signal ──────────────────────────────────────────────────────
    @property
    def n_rollouts(self) -> int:
        return len(self.rollouts)

    @property
    def n_verified(self) -> int:
        return sum(1 for r in self.rollouts if r.verified)

    @property
    def n_held_out_verified(self) -> int:
        return sum(1 for r in self.rollouts if r.verified and r.held_out)

    @property
    def mean_reward(self) -> float:
        return (sum(r.reward for r in self.rollouts) / len(self.rollouts)) if self.rollouts else 0.0

    @property
    def has_learnable_signal(self) -> bool:
        """A group teaches something only if rewards vary (≥1 pass and ≥1 fail), or
        there is at least one verified rollout to rejection-sample. A group where all
        rollouts share the same reward gives GRPO zero advantage gradient."""
        rewards = {r.reward for r in self.rollouts}
        return self.n_verified > 0 and len(rewards) > 1

    def oracle_block(self) -> Dict[str, Any]:
        """The teacher-independence provenance, asserted in-band."""
        return {
            "kind": "completion_gate",
            "reward_source": "model_independent",
            "judge_in_reward_loop": False,
            "held_out_available": self.n_held_out_verified > 0,
            "reward_baseline": self.mean_reward,
        }

    def reward_summary(self) -> Dict[str, Any]:
        return {
            "n_rollouts": self.n_rollouts,
            "n_verified": self.n_verified,
            "n_held_out_verified": self.n_held_out_verified,
            "max_reward": max((r.reward for r in self.rollouts), default=0.0),
            "mean_reward": self.mean_reward,
            "has_learnable_signal": self.has_learnable_signal,
        }

    def supported_methods(self) -> List[str]:
        methods: List[str] = []
        if self.n_verified > 0:
            methods += ["sft", "rft", "rejection_sampling", "grpo", "rlvr"]
        if self.n_verified > 0 and self.n_verified < self.n_rollouts:
            methods += ["dpo", "orpo"]
        return sorted({m for m in methods if m in RLVR_METHODS})

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": RLVR_GROUP_SCHEMA,
            "group_id": self.group_id,
            "tenant_id": self.tenant_id,
            "repo_id": self.repo_id,
            "dataset_family": self.dataset_family,
            "scope": self.scope,
            "task": self.task,
            "policy": self.policy,
            "oracle": self.oracle_block(),
            "reward_summary": self.reward_summary(),
            "supported_methods": self.supported_methods(),
            "rollouts": [r.to_dict() for r in self.rollouts],
            "safety": self.safety,
            "approval": self.approval,
            "created_at": self.created_at,
        }


def compute_group_advantages(rollouts: Sequence[RLVRRollout]) -> None:
    """GRPO-style group-relative advantage: ``advantage_i = reward_i - mean(reward)``.

    No learned value model — the baseline is the group mean, which is the whole point
    of group-relative RL on verifiable rewards. Mutates each rollout's ``advantage``.
    """
    if not rollouts:
        return
    baseline = sum(r.reward for r in rollouts) / len(rollouts)
    for r in rollouts:
        r.advantage = r.reward - baseline


def build_rollout_group(
    *,
    task: Dict[str, Any],
    policy: Dict[str, Any],
    attempts: Sequence[Tuple[str, VerificationRecord]],
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    dataset_family: str = "policy_playbook",
    scope: str = "tenant",
    safety: Optional[Dict[str, Any]] = None,
    approval: Optional[Dict[str, Any]] = None,
) -> RLVRRolloutGroup:
    """Build a rollout group from a task and a list of (trajectory_summary, VerificationRecord).

    Each ``VerificationRecord`` is the model-independent grade for one attempt (produced
    by ``hermes_cli.verification_evidence`` from the completion gate). Rewards and
    group-relative advantages are computed from those grades alone — no model judgment.
    """
    task_id = str(task.get("task_id") or task.get("goal") or "task")
    rollouts: List[RLVRRollout] = []
    for idx, (summary, record) in enumerate(attempts):
        block = record.to_evidence_block()
        reward = reward_from_verification(block)
        rollouts.append(
            RLVRRollout(
                rollout_id=_stable_id("roll", task_id, idx, record.evidence_sha256),
                attempt_index=idx,
                trajectory_ref=record.evidence_uri,
                trajectory_summary=str(summary or "")[:2000],
                verification=block,
                reward=reward,
                held_out=bool(record.held_out),
                verified=reward >= 1.0,
                checks_passed_fraction=_checks_passed_fraction(block),
            )
        )
    compute_group_advantages(rollouts)
    group_id = _stable_id(
        "rlvrgrp", task_id, tenant_id, repo_id,
        *[r.verification.get("evidence_sha256") for r in rollouts],
    )
    return RLVRRolloutGroup(
        group_id=group_id,
        task=dict(task),
        policy=dict(policy),
        rollouts=rollouts,
        tenant_id=tenant_id,
        repo_id=repo_id,
        dataset_family=dataset_family,
        scope=scope,
        safety=dict(safety or {}),
        approval=dict(approval or {}),
        created_at=_now(),
    )


# ── derivations into the existing mlops_corpus shapes ───────────────────────

def derive_sft_examples(group: RLVRRolloutGroup) -> List[Any]:
    """Verified rollouts → SFTMessageRecord (rejection-sampling fine-tune set)."""
    from hermes_cli.mlops_corpus import SFTMessageRecord

    out: List[Any] = []
    prompt = str(group.task.get("prompt_summary") or group.task.get("goal") or "")
    for r in group.rollouts:
        if not r.verified:
            continue
        out.append(
            SFTMessageRecord(
                dataset_family=group.dataset_family,
                messages=[
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": r.trajectory_summary},
                ],
                metadata={
                    "group_id": group.group_id,
                    "rollout_id": r.rollout_id,
                    "reward": r.reward,
                    "held_out": r.held_out,
                    "reward_source": "model_independent",
                    "verification_sha256": r.verification.get("evidence_sha256"),
                },
            )
        )
    return out


def derive_preference_pairs(group: RLVRRolloutGroup) -> List[Any]:
    """Best verified rollout (chosen) vs worst failing rollout (rejected) → DPO pair."""
    from hermes_cli.mlops_corpus import PreferencePairRecord

    verified = [r for r in group.rollouts if r.verified]
    failing = [r for r in group.rollouts if not r.verified]
    if not verified or not failing:
        return []
    chosen = max(verified, key=lambda r: (r.held_out, r.checks_passed_fraction))
    rejected = min(failing, key=lambda r: r.checks_passed_fraction)
    prompt = str(group.task.get("prompt_summary") or group.task.get("goal") or "")
    return [
        PreferencePairRecord(
            dataset_family=group.dataset_family,
            prompt_summary=prompt,
            chosen=chosen.trajectory_summary,
            rejected=rejected.trajectory_summary,
            metadata={
                "group_id": group.group_id,
                "chosen_rollout_id": chosen.rollout_id,
                "rejected_rollout_id": rejected.rollout_id,
                "chosen_reward": chosen.reward,
                "rejected_reward": rejected.reward,
                "reward_source": "model_independent",
            },
        )
    ]


# ── persistence (embedded in the SessionDB substrate) ───────────────────────

def ensure_rlvr_schema(db: SessionDB) -> None:
    def _do(conn):
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hermes_rlvr_rollout_groups (
                group_id TEXT PRIMARY KEY,
                tenant_id TEXT,
                repo_id TEXT,
                dataset_family TEXT NOT NULL,
                scope TEXT NOT NULL,
                task_json TEXT,
                policy_json TEXT,
                oracle_json TEXT,
                reward_summary_json TEXT,
                supported_methods_json TEXT,
                rollouts_json TEXT,
                safety_json TEXT,
                approval_json TEXT,
                has_learnable_signal INTEGER NOT NULL DEFAULT 0,
                n_verified INTEGER NOT NULL DEFAULT 0,
                n_held_out_verified INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_hermes_rlvr_scope
                ON hermes_rlvr_rollout_groups(
                    tenant_id, repo_id, dataset_family, has_learnable_signal, updated_at DESC
                )
            """
        )

    db._execute_write(_do)


def upsert_rollout_group(db: SessionDB, group: RLVRRolloutGroup) -> RLVRRolloutGroup:
    ensure_rlvr_schema(db)
    now = _now()
    data = group.to_dict()

    def _do(conn):
        conn.execute(
            """
            INSERT INTO hermes_rlvr_rollout_groups (
                group_id, tenant_id, repo_id, dataset_family, scope,
                task_json, policy_json, oracle_json, reward_summary_json,
                supported_methods_json, rollouts_json, safety_json, approval_json,
                has_learnable_signal, n_verified, n_held_out_verified,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(group_id) DO UPDATE SET
                tenant_id = excluded.tenant_id,
                repo_id = excluded.repo_id,
                dataset_family = excluded.dataset_family,
                scope = excluded.scope,
                task_json = excluded.task_json,
                policy_json = excluded.policy_json,
                oracle_json = excluded.oracle_json,
                reward_summary_json = excluded.reward_summary_json,
                supported_methods_json = excluded.supported_methods_json,
                rollouts_json = excluded.rollouts_json,
                safety_json = excluded.safety_json,
                approval_json = excluded.approval_json,
                has_learnable_signal = excluded.has_learnable_signal,
                n_verified = excluded.n_verified,
                n_held_out_verified = excluded.n_held_out_verified,
                updated_at = excluded.updated_at
            """,
            (
                group.group_id,
                group.tenant_id,
                group.repo_id,
                group.dataset_family,
                group.scope,
                _json_dumps(data["task"]),
                _json_dumps(data["policy"]),
                _json_dumps(data["oracle"]),
                _json_dumps(data["reward_summary"]),
                _json_dumps(data["supported_methods"]),
                _json_dumps(data["rollouts"]),
                _json_dumps(data["safety"]),
                _json_dumps(data["approval"]),
                1 if group.has_learnable_signal else 0,
                group.n_verified,
                group.n_held_out_verified,
                group.created_at or now,
                now,
            ),
        )

    db._execute_write(_do)
    return group


def _row_to_group(row: Any) -> RLVRRolloutGroup:
    rollouts = [
        RLVRRollout(
            rollout_id=r.get("rollout_id", ""),
            attempt_index=int(r.get("attempt_index", 0)),
            trajectory_ref=r.get("trajectory_ref", ""),
            trajectory_summary=r.get("trajectory_summary", ""),
            verification=r.get("verification") or {},
            reward=float(r.get("reward", 0.0)),
            advantage=float(r.get("advantage", 0.0)),
            held_out=bool(r.get("held_out", False)),
            verified=bool(r.get("verified", False)),
            checks_passed_fraction=float(r.get("checks_passed_fraction", 0.0)),
        )
        for r in _json_loads(row["rollouts_json"])
    ]
    return RLVRRolloutGroup(
        group_id=row["group_id"],
        task=_json_loads(row["task_json"]),
        policy=_json_loads(row["policy_json"]),
        rollouts=rollouts,
        tenant_id=row["tenant_id"],
        repo_id=row["repo_id"],
        dataset_family=row["dataset_family"],
        scope=row["scope"],
        safety=_json_loads(row["safety_json"]),
        approval=_json_loads(row["approval_json"]),
        created_at=float(row["created_at"]),
    )


def get_rollout_group(db: SessionDB, group_id: str) -> Optional[RLVRRolloutGroup]:
    ensure_rlvr_schema(db)
    row = db._conn.execute(
        "SELECT * FROM hermes_rlvr_rollout_groups WHERE group_id = ?", (group_id,)
    ).fetchone()
    return _row_to_group(row) if row is not None else None


def list_rollout_groups(
    db: SessionDB,
    *,
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    dataset_family: Optional[str] = None,
    learnable_only: bool = False,
    limit: int = 50,
) -> List[RLVRRolloutGroup]:
    ensure_rlvr_schema(db)
    clauses: List[str] = []
    params: List[Any] = []
    if tenant_id is not None:
        clauses.append("tenant_id = ?")
        params.append(tenant_id)
    if repo_id is not None:
        clauses.append("repo_id = ?")
        params.append(repo_id)
    if dataset_family is not None:
        clauses.append("dataset_family = ?")
        params.append(dataset_family)
    if learnable_only:
        clauses.append("has_learnable_signal = 1")
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = db._conn.execute(
        f"SELECT * FROM hermes_rlvr_rollout_groups{where} "
        f"ORDER BY updated_at DESC LIMIT ?",
        (*params, int(limit)),
    ).fetchall()
    return [_row_to_group(row) for row in rows]
