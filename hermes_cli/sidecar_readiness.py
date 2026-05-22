"""Service readiness helpers for runtime learning sidecars.

These helpers are deterministic control-plane checks. They model service,
timer, and one-shot sidecar readiness without starting unbounded daemons or
calling providers. Optional runner callbacks let tests and operators exercise a
bounded service-equivalent pass.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import time
import uuid
from typing import Any, Callable, Mapping

from hermes_cli.platform_hardening import (
    BudgetLimit,
    BudgetUsage,
    SidecarBudgetRequest,
    evaluate_sidecar_budget,
)
from hermes_state import SessionDB


SIDECAR_DEFINITIONS: dict[str, dict[str, Any]] = {
    "curator": {"category": "learning", "tier": "strong_reasoning", "interval_seconds": 300, "deadline_seconds": 120, "llm_backed": True},
    "learning_judge": {"category": "approval", "tier": "strong_reasoning", "interval_seconds": 300, "deadline_seconds": 120, "llm_backed": True},
    "dreaming": {"category": "proposal", "tier": "strong_reasoning", "interval_seconds": 3600, "deadline_seconds": 180, "llm_backed": True},
    "wiki": {"category": "memory", "tier": "programmatic", "interval_seconds": 900, "deadline_seconds": 60, "llm_backed": False},
    "bus_consumer": {"category": "bus", "tier": "programmatic", "interval_seconds": 60, "deadline_seconds": 30, "llm_backed": False},
    "sync": {"category": "global_memory", "tier": "programmatic", "interval_seconds": 300, "deadline_seconds": 60, "llm_backed": False},
    "progress_summarizer": {"category": "progress", "tier": "cheap_reasoning", "interval_seconds": 30, "deadline_seconds": 20, "llm_backed": True},
    "housekeeping": {"category": "maintenance", "tier": "programmatic", "interval_seconds": 3600, "deadline_seconds": 60, "llm_backed": False},
}


def _now() -> float:
    return time.time()


def ensure_sidecar_readiness_schema(db: SessionDB) -> None:
    def _do(conn):
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hermes_sidecar_leases (
                sidecar_name TEXT PRIMARY KEY,
                lease_owner TEXT NOT NULL,
                expires_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )

    db._execute_write(_do)


@dataclass(frozen=True)
class SidecarReadinessItem:
    name: str
    category: str
    status: str
    mode: str
    tier: str
    lock_acquired: bool
    lease_owner: str
    interval_seconds: float
    deadline_seconds: float
    backlog_count: int
    backlog_limit: int
    budget_status: str
    degraded_reason: str = ""
    foreground_blocking: bool = False
    runner_status: str = "not_run"
    runner_ref: str = ""
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SidecarReadinessResult:
    status: str
    mode: str
    run_once: bool
    lease_owner: str
    checked: int
    ready: int
    degraded: int
    skipped: int
    foreground_blocking: bool
    items: list[SidecarReadinessItem]
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["items"] = [item.to_dict() for item in self.items]
        return data


def _sidecar_config(config: Mapping[str, Any], name: str) -> dict[str, Any]:
    runtime = ((config or {}).get("supervisor") or {}).get("sidecar_services") or {}
    if not isinstance(runtime, Mapping):
        runtime = {}
    value = runtime.get(name) or {}
    return dict(value) if isinstance(value, Mapping) else {}


def _budget_config(config: Mapping[str, Any]) -> tuple[BudgetLimit, BudgetUsage]:
    raw = ((config or {}).get("supervisor") or {}).get("sidecar_budget") or {}
    if not isinstance(raw, Mapping):
        raw = {}
    limits = raw.get("limits") or {}
    usage = raw.get("usage") or {}
    if not isinstance(limits, Mapping):
        limits = {}
    if not isinstance(usage, Mapping):
        usage = {}
    return (
        BudgetLimit(
            tenant_cost=float(limits.get("tenant_cost", 999999)),
            task_cost=float(limits.get("task_cost", 999999)),
            daily_cost=float(limits.get("daily_cost", 999999)),
            tenant_tokens=int(limits.get("tenant_tokens", 999999999)),
            task_tokens=int(limits.get("task_tokens", 999999999)),
        ),
        BudgetUsage(
            tenant_cost=float(usage.get("tenant_cost", 0)),
            task_cost=float(usage.get("task_cost", 0)),
            daily_cost=float(usage.get("daily_cost", 0)),
            tenant_tokens=int(usage.get("tenant_tokens", 0)),
            task_tokens=int(usage.get("task_tokens", 0)),
        ),
    )


def _acquire_lock(
    db: SessionDB,
    name: str,
    *,
    owner: str,
    now: float,
    lease_seconds: float,
) -> tuple[bool, str]:
    ensure_sidecar_readiness_schema(db)

    def _do(conn):
        row = conn.execute(
            "SELECT lease_owner, expires_at FROM hermes_sidecar_leases WHERE sidecar_name = ?",
            (name,),
        ).fetchone()
        if row is not None and float(row["expires_at"] or 0) > now and str(row["lease_owner"]) != owner:
            return False, str(row["lease_owner"])
        conn.execute(
            """
            INSERT INTO hermes_sidecar_leases (sidecar_name, lease_owner, expires_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(sidecar_name) DO UPDATE SET
                lease_owner = excluded.lease_owner,
                expires_at = excluded.expires_at,
                updated_at = excluded.updated_at
            """,
            (name, owner, now + max(1.0, float(lease_seconds)), now),
        )
        return True, owner

    return db._execute_write(_do)


def _selected_sidecars(sidecars: list[str] | tuple[str, ...] | None) -> list[str]:
    if not sidecars:
        return list(SIDECAR_DEFINITIONS)
    selected = []
    for name in sidecars:
        key = str(name).strip()
        if key not in SIDECAR_DEFINITIONS:
            raise ValueError(f"unknown sidecar: {key}")
        selected.append(key)
    return selected


def run_sidecar_readiness(
    db: SessionDB,
    *,
    config: Mapping[str, Any] | None = None,
    mode: str = "oneshot",
    run_once: bool = False,
    sidecars: list[str] | tuple[str, ...] | None = None,
    now: float | None = None,
    lease_owner: str | None = None,
    runners: Mapping[str, Callable[[str, dict[str, Any]], Any]] | None = None,
) -> SidecarReadinessResult:
    config_map = dict(config or {})
    current = _now() if now is None else float(now)
    owner = lease_owner or f"sidecar-{uuid.uuid4().hex[:12]}"
    names = _selected_sidecars(sidecars)
    limits, usage = _budget_config(config_map)
    items: list[SidecarReadinessItem] = []
    errors: list[str] = []

    for name in names:
        definition = SIDECAR_DEFINITIONS[name]
        cfg = _sidecar_config(config_map, name)
        enabled = bool(cfg.get("enabled", True))
        interval = float(cfg.get("interval_seconds", definition["interval_seconds"]) or definition["interval_seconds"])
        deadline = float(cfg.get("deadline_seconds", definition["deadline_seconds"]) or definition["deadline_seconds"])
        backlog_count = int(cfg.get("backlog_count", 0) or 0)
        backlog_limit = int(cfg.get("backlog_limit", 1000) or 1000)
        estimated_tokens = int(cfg.get("estimated_tokens", 0) or 0)
        estimated_cost = float(cfg.get("estimated_cost", 0.0) or 0.0)
        llm_backed = bool(cfg.get("llm_backed", definition["llm_backed"]))
        tier = str(cfg.get("tier", definition["tier"]))
        lock_acquired, lock_owner = _acquire_lock(
            db,
            name,
            owner=owner,
            now=current,
            lease_seconds=deadline,
        )
        budget = evaluate_sidecar_budget(
            SidecarBudgetRequest(
                tenant_id=str(cfg.get("tenant_id", "")),
                task_id=str(cfg.get("task_id", "")),
                sidecar_role=name,
                llm_backed=llm_backed,
                estimated_tokens=estimated_tokens,
                estimated_cost=estimated_cost,
                escalation_reason="service_readiness",
                degrade_tier="programmatic" if llm_backed else None,
            ),
            limits=limits,
            usage=usage,
        )
        reasons: list[str] = []
        if not enabled:
            reasons.append("disabled")
        if not lock_acquired:
            reasons.append("lock_held")
        if backlog_count > backlog_limit:
            reasons.append("backlog_limit_exceeded")
        if not budget.allowed:
            reasons.append(f"budget_{budget.status}")

        status = "ready" if not reasons else "degraded"
        if not enabled:
            status = "skipped"
        runner_status = "not_run"
        runner_ref = ""
        item_errors: list[str] = []
        if run_once and status == "ready":
            runner = (runners or {}).get(name)
            if runner is None:
                runner_status = "ready_no_runner"
            else:
                try:
                    result = runner(name, {"mode": mode, "deadline_seconds": deadline, "lease_owner": owner})
                    runner_status = str((result or {}).get("status", "completed")) if isinstance(result, Mapping) else "completed"
                    runner_ref = str((result or {}).get("ref", "")) if isinstance(result, Mapping) else ""
                except Exception as exc:
                    runner_status = "error"
                    status = "degraded"
                    item_errors.append(str(exc))
                    errors.append(f"{name}: {exc}")

        items.append(
            SidecarReadinessItem(
                name=name,
                category=str(definition["category"]),
                status=status,
                mode=str(mode),
                tier=tier,
                lock_acquired=lock_acquired,
                lease_owner=lock_owner,
                interval_seconds=interval,
                deadline_seconds=deadline,
                backlog_count=backlog_count,
                backlog_limit=backlog_limit,
                budget_status=budget.status,
                degraded_reason=",".join(reasons),
                foreground_blocking=False,
                runner_status=runner_status,
                runner_ref=runner_ref,
                errors=item_errors,
            )
        )

    ready = sum(1 for item in items if item.status == "ready")
    degraded = sum(1 for item in items if item.status == "degraded")
    skipped = sum(1 for item in items if item.status == "skipped")
    return SidecarReadinessResult(
        status="ready" if degraded == 0 else "degraded",
        mode=str(mode),
        run_once=bool(run_once),
        lease_owner=owner,
        checked=len(items),
        ready=ready,
        degraded=degraded,
        skipped=skipped,
        foreground_blocking=False,
        items=items,
        errors=errors,
    )
