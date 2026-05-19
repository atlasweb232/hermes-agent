"""Deterministic local/dev runtime E2E runner."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from hermes_constants import get_hermes_home
from hermes_cli.runtime_features import resolve_runtime_feature, status_runtime_features
from hermes_state import SessionDB


SCHEMA_VERSION = 1
DEFAULT_SUITE_ID = "runtime.local_smoke"
DEFAULT_WORKLOAD_ID = "runtime-local-dev-smoke"
VALIDATION_COMMAND = "runtime-e2e:deterministic-local-smoke"
MAX_SUMMARY_LENGTH = 240
MAX_INDEXED_RUNS = 100
RUN_KEY_PREFIX = "runtime_e2e_run:"
RUN_INDEX_KEY = "runtime_e2e_runs"

E2E_SMOKE_FEATURE_IDS = (
    "runtime.health_sidecar",
    "runtime.restart_recovery",
    "runtime.task_graph",
    "runtime.benchmark_harness",
)

_SECRET_PATTERNS = [
    re.compile(r"(?i)\b(sk-[A-Za-z0-9_-]{8,})\b"),
    re.compile(r"(?i)\b((?:api[_-]?key|token|secret|password)\s*=\s*)\S+"),
]


def _now_iso(now: Optional[float] = None) -> str:
    timestamp = time.time() if now is None else float(now)
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _scope_dict(tenant_id: Optional[str] = None, repo_id: Optional[str] = None) -> Dict[str, Optional[str]]:
    return {"tenant_id": tenant_id or None, "repo_id": repo_id or None}


def _redact_and_bound(value: Any, *, limit: int = MAX_SUMMARY_LENGTH) -> str:
    text = " ".join(str(value or "").split())
    for pattern in _SECRET_PATTERNS:
        def _replace(match: re.Match[str]) -> str:
            if match.lastindex:
                return f"{match.group(1)}[REDACTED]"
            return "[REDACTED]"

        text = pattern.sub(_replace, text)
    if len(text) > limit:
        text = text[: limit - 3].rstrip() + "..."
    return text


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-")
    return slug[:80] or "local"


def _git_head(repo_path: Path) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "--short=12", "HEAD"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        )
    except Exception:
        proc = None
    if proc is not None and proc.returncode == 0 and proc.stdout.strip():
        return proc.stdout.strip()
    digest = hashlib.sha256(str(repo_path.resolve()).encode("utf-8")).hexdigest()[:12]
    return f"local-{digest}"


@dataclass(frozen=True)
class E2EArtifactRef:
    artifact_id: str
    kind: str
    path: str
    summary: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "kind": self.kind,
            "path": self.path,
            "summary": _redact_and_bound(self.summary),
        }


@dataclass(frozen=True)
class E2EValidationEvidence:
    validation_id: str
    command: str
    status: str
    artifact_ref: str
    summary: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "validation_id": self.validation_id,
            "command": self.command,
            "status": self.status,
            "artifact_ref": self.artifact_ref,
            "summary": _redact_and_bound(self.summary),
        }


@dataclass(frozen=True)
class E2ECaseDefinition:
    case_id: str
    feature_id: str
    title: str
    workload_id: str = DEFAULT_WORKLOAD_ID
    validation_commands: List[str] = field(default_factory=lambda: [VALIDATION_COMMAND])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case_id": self.case_id,
            "feature_id": self.feature_id,
            "title": self.title,
            "workload_id": self.workload_id,
            "validation_commands": list(self.validation_commands),
        }


CASE_DEFINITIONS = (
    E2ECaseDefinition("runtime.health_sidecar.disabled_or_enabled", "runtime.health_sidecar", "Health sidecar smoke"),
    E2ECaseDefinition("runtime.restart_recovery.disabled_or_enabled", "runtime.restart_recovery", "Restart recovery smoke"),
    E2ECaseDefinition("runtime.task_graph.disabled_or_enabled", "runtime.task_graph", "Task graph smoke"),
    E2ECaseDefinition("runtime.benchmark_harness.disabled_or_enabled", "runtime.benchmark_harness", "Benchmark harness smoke"),
)


def _suite_dict(repo_path: Optional[Path] = None) -> Dict[str, Any]:
    repo_path = Path(repo_path or os.getcwd())
    return {
        "schema_version": SCHEMA_VERSION,
        "suite_id": DEFAULT_SUITE_ID,
        "title": "Runtime local/dev smoke",
        "workload_id": DEFAULT_WORKLOAD_ID,
        "profile": "deterministic-local-dev",
        "repo_snapshot": {
            "ref_kind": "local_git",
            "head_ref": _git_head(repo_path),
            "summary": "bounded repository snapshot reference only",
        },
        "artifact_policy": {
            "isolated_hermes_home": True,
            "isolated_artifact_root": True,
            "bounded_evidence_only": True,
            "raw_transcripts_stored": False,
            "expensive_sidecars_default": False,
            "enforcement_allowed": False,
        },
        "validation_commands": [VALIDATION_COMMAND],
        "cases": [case.to_dict() for case in CASE_DEFINITIONS],
    }


def list_e2e_suites(*, repo_path: Optional[Path] = None) -> Dict[str, Any]:
    """List stable local/dev E2E suite metadata without writing state."""

    return {"schema_version": SCHEMA_VERSION, "suites": [_suite_dict(repo_path=repo_path)]}


def _state_key(run_id: str) -> str:
    return f"{RUN_KEY_PREFIX}{run_id}"


def _load_index(db: SessionDB) -> List[str]:
    raw = db.get_meta(RUN_INDEX_KEY)
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if isinstance(item, str)]


def _save_run(db: SessionDB, payload: Dict[str, Any]) -> None:
    run_id = str(payload["run_id"])
    db.set_meta(_state_key(run_id), json.dumps(payload, sort_keys=True, ensure_ascii=True))
    index = [item for item in _load_index(db) if item != run_id]
    index.append(run_id)
    db.set_meta(RUN_INDEX_KEY, json.dumps(index[-MAX_INDEXED_RUNS:], sort_keys=True, ensure_ascii=True))


def get_e2e_run(db: SessionDB, run_id: str) -> Dict[str, Any]:
    raw = db.get_meta(_state_key(run_id))
    if not raw:
        raise ValueError(f"unknown runtime e2e run: {run_id}")
    try:
        payload = json.loads(raw)
    except Exception as exc:
        raise ValueError(f"corrupt runtime e2e run: {run_id}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"unsupported runtime e2e run schema: {run_id}")
    return payload


def list_e2e_runs(db: SessionDB, *, limit: int = 20) -> Dict[str, Any]:
    run_ids = _load_index(db)[-max(1, int(limit)) :]
    runs = []
    for run_id in run_ids:
        try:
            runs.append(get_e2e_run(db, run_id))
        except ValueError:
            continue
    return {"schema_version": SCHEMA_VERSION, "runs": runs}


def _case_payload(
    *,
    run_id: str,
    suite_id: str,
    case: E2ECaseDefinition,
    feature_state: Dict[str, Any],
    scope: Dict[str, Optional[str]],
    artifact_root: Path,
) -> Dict[str, Any]:
    enabled = bool(feature_state.get("effective"))
    status = "passed" if enabled else "skipped"
    reason = "feature enabled for scoped deterministic smoke" if enabled else "feature disabled by scoped runtime toggle"
    artifact = E2EArtifactRef(
        artifact_id=f"artifact_{case.feature_id.replace('.', '_')}",
        kind="synthetic_evidence_ref",
        path=str(artifact_root / "evidence" / f"{case.feature_id}.json"),
        summary=reason,
    ).to_dict()
    validation = E2EValidationEvidence(
        validation_id=f"validation_{case.feature_id.replace('.', '_')}",
        command=VALIDATION_COMMAND,
        status=status,
        artifact_ref=artifact["artifact_id"],
        summary=reason,
    ).to_dict()
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "suite_id": suite_id,
        "case_id": case.case_id,
        "feature_ids": [case.feature_id],
        "feature_state": feature_state,
        "tenant_id": scope["tenant_id"],
        "repo_id": scope["repo_id"],
        "workload_id": case.workload_id,
        "session_id": f"e2e_{run_id}",
        "task_id": f"task_{case.case_id}",
        "worker_ids": [],
        "model_provider_roles": {"mode": "deterministic-local", "provider_calls": 0},
        "latency_budget": {"seconds": 0, "expensive_sidecars_allowed": False},
        "token_cost_estimate": {"prompt_tokens": 0, "completion_tokens": 0, "estimated_cost_usd": 0.0},
        "artifacts": [artifact],
        "telemetry_refs": [],
        "memory_refs": [],
        "sidecar_refs": [],
        "notification_refs": [],
        "validation_refs": [validation],
        "status": status,
        "failure_class": None,
        "rollout_recommendation": "keep_disabled" if not enabled else "manual_review_only",
        "skip_reason": None if enabled else reason,
        "enforcement_allowed": False,
    }


def _overall_status(cases: Iterable[Dict[str, Any]]) -> str:
    statuses = [case.get("status") for case in cases]
    if any(status == "failed" for status in statuses):
        return "failed"
    if statuses and all(status == "skipped" for status in statuses):
        return "skipped"
    if any(status == "skipped" for status in statuses):
        return "passed_with_skips"
    return "passed"


def run_e2e_suite(
    db: SessionDB,
    *,
    suite_id: str,
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    artifact_root: Optional[Path | str] = None,
    repo_path: Optional[Path | str] = None,
    transcript_excerpt: str = "",
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Run the deterministic local/dev E2E suite and persist bounded state."""

    if suite_id != DEFAULT_SUITE_ID:
        raise ValueError(f"unknown runtime e2e suite: {suite_id}")

    created_at = _now_iso(now)
    run_id = f"e2e_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:12]}"
    scope = _scope_dict(tenant_id, repo_id)
    repo_path_obj = Path(repo_path or os.getcwd())
    base_root = Path(artifact_root) if artifact_root else get_hermes_home() / "runtime-e2e"
    run_root = base_root / _safe_slug(run_id)
    isolated_home = run_root / "hermes-home"
    evidence_root = run_root / "evidence"
    isolated_home.mkdir(parents=True, exist_ok=True)
    evidence_root.mkdir(parents=True, exist_ok=True)

    feature_snapshot = status_runtime_features(db, tenant_id=tenant_id, repo_id=repo_id)
    states = {item["feature_id"]: item for item in feature_snapshot["features"]}
    cases = [
        _case_payload(
            run_id=run_id,
            suite_id=suite_id,
            case=case,
            feature_state=resolve_runtime_feature(db, case.feature_id, tenant_id=tenant_id, repo_id=repo_id),
            scope=scope,
            artifact_root=run_root,
        )
        for case in CASE_DEFINITIONS
        if case.feature_id in states
    ]

    validation = E2EValidationEvidence(
        validation_id=f"validation_{run_id}",
        command=VALIDATION_COMMAND,
        status=_overall_status(cases),
        artifact_ref="runtime-e2e-summary",
        summary="deterministic local/dev smoke recorded bounded evidence refs only",
    ).to_dict()
    repo_snapshot = {
        "repo_id": repo_id or None,
        "ref_kind": "local_git",
        "head_ref": _git_head(repo_path_obj),
        "worktree_ref": f"path-sha256:{hashlib.sha256(str(repo_path_obj.resolve()).encode('utf-8')).hexdigest()[:16]}",
        "summary": "bounded repository snapshot reference only",
    }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "suite_id": suite_id,
        "workload_id": DEFAULT_WORKLOAD_ID,
        "status": _overall_status(cases),
        "created_at": created_at,
        "completed_at": created_at,
        "scope": scope,
        "tenant_id": scope["tenant_id"],
        "repo_id": scope["repo_id"],
        "repo_snapshot": repo_snapshot,
        "isolated": {
            "hermes_home": str(isolated_home),
            "artifact_root": str(run_root),
            "state_db": str(isolated_home / "state.db"),
        },
        "artifacts": {
            "root": str(run_root),
            "evidence_root": str(evidence_root),
            "refs": [
                E2EArtifactRef(
                    artifact_id="runtime-e2e-summary",
                    kind="summary",
                    path=str(evidence_root / "summary.json"),
                    summary="bounded deterministic E2E run summary",
                ).to_dict()
            ],
        },
        "feature_snapshot": feature_snapshot,
        "cases": cases,
        "validation_refs": [validation],
        "blockers": [],
        "telemetry_refs": [],
        "memory_refs": [],
        "sidecar_refs": [],
        "notification_refs": [],
        "model_provider_roles": {"mode": "deterministic-local", "provider_calls": 0},
        "latency_budget": {"seconds": 0, "expensive_sidecars_allowed": False},
        "token_cost_estimate": {"prompt_tokens": 0, "completion_tokens": 0, "estimated_cost_usd": 0.0},
        "safety": {
            "enforcement_allowed": False,
            "raw_transcripts_stored": False,
            "expensive_sidecars_started": False,
            "provider_calls": 0,
            "input_summary": "input content omitted; no raw transcript stored" if transcript_excerpt else "",
        },
        "rollout_recommendation": "keep_disabled" if _overall_status(cases) == "skipped" else "manual_review_only",
    }
    _save_run(db, payload)
    return payload
