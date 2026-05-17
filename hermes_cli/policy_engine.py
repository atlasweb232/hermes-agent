"""Deterministic runtime policy audit/evaluation helpers."""

from __future__ import annotations

import json
import re
import shlex
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from hermes_cli.config import load_config
from hermes_state import SessionDB


@dataclass
class PolicyDecision:
    status: str
    mode: str
    original_command: str
    effective_command: str
    matches: List[Dict[str, Any]] = field(default_factory=list)
    audit_id: str = field(default_factory=lambda: f"pol_{uuid.uuid4().hex[:16]}")
    created_at: float = field(default_factory=time.time)
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _command_tokens(command: str) -> List[str]:
    try:
        return shlex.split(command)
    except Exception:
        return command.split()


def _normalize_command(command: str) -> str:
    return " ".join(_command_tokens(command)).strip()


def _command_contains_secret(command: str) -> bool:
    return bool(
        re.search(
            r"(sk-[A-Za-z0-9_-]{12,}|AKIA[0-9A-Z]{16}|password\s*=|token\s*=|secret\s*=)",
            command,
            re.IGNORECASE,
        )
    )


def _is_destructive(command: str) -> bool:
    normalized = _normalize_command(command)
    return bool(
        re.search(
            r"(^|\s)(rm\s+-rf|git\s+reset\s+--hard|mkfs|dd\s+if=|shutdown|reboot)(\s|$)",
            normalized,
        )
    )


def _policy_matches_command(candidate: Dict[str, Any], command: str) -> Optional[Dict[str, Any]]:
    evidence = candidate.get("evidence_json") if isinstance(candidate.get("evidence_json"), dict) else {}
    if evidence.get("policy_type") != "command_repair":
        return None
    failed_path = str(evidence.get("failed_path") or "").strip()
    working_path = str(evidence.get("working_path") or "").strip()
    if not failed_path or not working_path:
        return None

    normalized_command = _normalize_command(command)
    normalized_failed = _normalize_command(failed_path)
    if not normalized_command.startswith(normalized_failed):
        return None

    return {
        "policy_id": candidate.get("id"),
        "kind": candidate.get("kind"),
        "claim": candidate.get("claim"),
        "score": candidate.get("score"),
        "status": candidate.get("status"),
        "policy_type": evidence.get("policy_type"),
        "policy_version": evidence.get("policy_version"),
        "source_record_id": evidence.get("source_record_id"),
        "failed_path": failed_path,
        "working_path": working_path,
        "action": "would_rewrite",
    }


def evaluate_command_policy(
    command: str,
    *,
    config: Optional[Dict[str, Any]] = None,
    db: Optional[SessionDB] = None,
) -> PolicyDecision:
    """Evaluate approved runtime policies for a command.

    Default mode is audit, so the command is never changed. This function is
    intentionally deterministic and does not parse raw curator prose.
    """
    if config is None:
        config = load_config()
    engine = (config.get("supervisor") or {}).get("policy_engine") or {}
    if not isinstance(engine, dict):
        engine = {}
    mode = str(engine.get("mode") or "audit").strip() or "audit"
    if engine.get("enabled", True) is False:
        return PolicyDecision(
            status="disabled",
            mode=mode,
            original_command=command,
            effective_command=command,
            notes="policy engine disabled",
        )
    if mode not in {"audit", "enforce"}:
        mode = "audit"
    if _command_contains_secret(command):
        return PolicyDecision(
            status="skipped",
            mode=mode,
            original_command=command,
            effective_command=command,
            notes="command contains secret-like text",
        )
    if _is_destructive(command):
        return PolicyDecision(
            status="skipped",
            mode=mode,
            original_command=command,
            effective_command=command,
            notes="destructive command skipped",
        )

    close_db = False
    if db is None:
        db = SessionDB()
        close_db = True
    try:
        matches: List[Dict[str, Any]] = []
        max_matches = max(1, int(engine.get("max_matches", 3) or 3))
        for status in ("approved", "applied"):
            rows = db.list_meta_candidates(status=status, limit=50)
            for candidate in rows:
                match = _policy_matches_command(candidate, command)
                if match:
                    matches.append(match)
                    if len(matches) >= max_matches:
                        break
            if len(matches) >= max_matches:
                break
    finally:
        if close_db:
            db.close()

    if not matches:
        return PolicyDecision(
            status="no_match",
            mode=mode,
            original_command=command,
            effective_command=command,
        )

    # Enforcement is deliberately not implemented yet; enforce mode is treated
    # as audit until the rewrite templating/approval layer lands.
    return PolicyDecision(
        status="matched",
        mode=mode,
        original_command=command,
        effective_command=command,
        matches=matches,
        notes="audit only; command unchanged",
    )


def escalate_approved_memory_to_policy_candidate(
    db: SessionDB,
    *,
    memory_candidate_id: str,
) -> Optional[str]:
    """Create a deterministic command-repair policy candidate from approved memory."""
    candidate = db.get_meta_candidate(memory_candidate_id)
    if candidate is None or candidate.get("status") not in {"approved", "applied"}:
        return None
    evidence = candidate.get("evidence_json") if isinstance(candidate.get("evidence_json"), dict) else {}
    failed_path = str(evidence.get("failed_path") or "").strip()
    working_path = str(evidence.get("working_path") or "").strip()
    if not failed_path or not working_path:
        return None
    policy_id = f"curpol_{memory_candidate_id}"
    db.upsert_meta_candidate(
        candidate_id=policy_id,
        kind="command_repair_policy",
        claim=f"Advisory command repair policy: prefer {working_path} after {failed_path} failures",
        evidence_json={
            "policy_type": "command_repair",
            "mode": "advisory",
            "source_candidate_id": memory_candidate_id,
            "failed_path": failed_path,
            "working_path": working_path,
            "validation": {"status": "valid", "eligible_for_approval": True, "errors": []},
        },
        score=float(candidate.get("score") or 0.0),
        status="proposed",
        tenant_id=candidate.get("tenant_id"),
        repo_id=candidate.get("repo_id"),
    )
    return policy_id


def compact_policy_metadata(decision: PolicyDecision) -> Optional[Dict[str, Any]]:
    if decision.status not in {"matched", "skipped"}:
        return None
    data = decision.to_dict()
    text = json.dumps(data, ensure_ascii=False, sort_keys=True)
    if len(text) > 4000:
        data["matches"] = data.get("matches", [])[:1]
        data["truncated"] = True
    return data
