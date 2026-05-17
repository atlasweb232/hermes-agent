"""Learning judge approval gate for Hermes meta-candidates.

The judge is an advisory auxiliary-model pass. It can approve, reject, or
escalate proposed candidates, but it does not enable runtime enforcement.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import re
import subprocess
import uuid
from typing import Any, Callable, Dict, List, Optional

from hermes_cli.config import load_config
from hermes_state import SessionDB


VALID_JUDGE_DECISIONS = {"approve", "reject", "needs_human"}
JUDGE_SCHEMA_KEYS = {
    "candidate_id",
    "decision",
    "confidence",
    "rationale",
    "risk_flags",
    "allow_enforcement",
}


class LearningJudgeParseError(ValueError):
    """Raised when judge output does not match the strict schema."""


@dataclass
class LearningJudgeConfig:
    enabled: bool = True
    provider: str = "codex"
    model: str = "codex"
    base_url: str = ""
    timeout_seconds: float = 300.0
    max_candidates: int = 10
    min_confidence: float = 0.75
    fail_closed: bool = True
    allow_enforcement_approval: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LearningJudgeDecision:
    candidate_id: str
    decision: str
    confidence: float
    rationale: str
    risk_flags: List[str] = field(default_factory=list)
    allow_enforcement: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LearningJudgeCandidateResult:
    candidate_id: str
    decision: str
    status: str
    confidence: float
    rationale: str
    risk_flags: List[str] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LearningJudgeRunResult:
    run_id: str
    status: str
    candidates_scanned: int
    candidates_judged: int
    approved: int
    rejected: int
    needs_human: int
    results: List[LearningJudgeCandidateResult] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    config: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def load_learning_judge_config(config: Optional[Dict[str, Any]] = None) -> LearningJudgeConfig:
    supervisor = (config or {}).get("supervisor", {})
    if not isinstance(supervisor, dict):
        supervisor = {}
    raw = supervisor.get("learning_judge", {})
    if not isinstance(raw, dict):
        raw = {}
    return LearningJudgeConfig(
        enabled=bool(raw.get("enabled", True)),
        provider=str(raw.get("provider", "codex") or "codex"),
        model=str(raw.get("model", "codex") or "codex"),
        base_url=str(raw.get("base_url", "") or ""),
        timeout_seconds=float(raw.get("timeout_seconds", 300) or 300),
        max_candidates=int(raw.get("max_candidates", 10) or 10),
        min_confidence=float(raw.get("min_confidence", 0.75) or 0.75),
        fail_closed=bool(raw.get("fail_closed", True)),
        allow_enforcement_approval=bool(raw.get("allow_enforcement_approval", False)),
    )


def _extract_json_object(raw: str) -> Dict[str, Any]:
    text = str(raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise LearningJudgeParseError("judge output did not contain a JSON object")
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise LearningJudgeParseError(f"judge output was not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise LearningJudgeParseError("judge output must be a JSON object")
    return payload


def parse_learning_judge_decision(raw: str, *, expected_candidate_id: Optional[str] = None) -> LearningJudgeDecision:
    payload = _extract_json_object(raw)
    extra = set(payload) - JUDGE_SCHEMA_KEYS
    missing = JUDGE_SCHEMA_KEYS - set(payload)
    if extra:
        raise LearningJudgeParseError(f"unexpected judge fields: {sorted(extra)}")
    if missing:
        raise LearningJudgeParseError(f"missing judge fields: {sorted(missing)}")

    candidate_id = str(payload["candidate_id"] or "").strip()
    if not candidate_id:
        raise LearningJudgeParseError("candidate_id is required")
    if expected_candidate_id and candidate_id != expected_candidate_id:
        raise LearningJudgeParseError(
            f"candidate_id mismatch: expected {expected_candidate_id}, got {candidate_id}"
        )

    decision = str(payload["decision"] or "").strip()
    if decision not in VALID_JUDGE_DECISIONS:
        raise LearningJudgeParseError(f"invalid decision: {decision}")

    try:
        confidence = float(payload["confidence"])
    except (TypeError, ValueError) as exc:
        raise LearningJudgeParseError("confidence must be numeric") from exc
    if confidence < 0.0 or confidence > 1.0:
        raise LearningJudgeParseError("confidence must be between 0 and 1")

    rationale = str(payload["rationale"] or "").strip()
    if not rationale:
        raise LearningJudgeParseError("rationale is required")

    risk_flags_raw = payload["risk_flags"]
    if not isinstance(risk_flags_raw, list) or not all(isinstance(item, str) for item in risk_flags_raw):
        raise LearningJudgeParseError("risk_flags must be a list of strings")

    allow_enforcement = payload["allow_enforcement"]
    if not isinstance(allow_enforcement, bool):
        raise LearningJudgeParseError("allow_enforcement must be boolean")

    return LearningJudgeDecision(
        candidate_id=candidate_id,
        decision=decision,
        confidence=confidence,
        rationale=rationale,
        risk_flags=[item.strip() for item in risk_flags_raw if item.strip()],
        allow_enforcement=allow_enforcement,
    )


def build_learning_judge_prompt(candidate: Dict[str, Any]) -> str:
    evidence = {
        "id": candidate.get("id"),
        "kind": candidate.get("kind"),
        "claim": candidate.get("claim"),
        "score": candidate.get("score"),
        "status": candidate.get("status"),
        "tenant_id": candidate.get("tenant_id"),
        "repo_id": candidate.get("repo_id"),
        "evidence_json": candidate.get("evidence_json"),
    }
    return (
        "You are the Hermes learning judge. Review one proposed learning candidate.\n"
        "Return only one strict JSON object with exactly these fields:\n"
        "{"
        "\"candidate_id\":\"string\","
        "\"decision\":\"approve|reject|needs_human\","
        "\"confidence\":0.0,"
        "\"rationale\":\"string\","
        "\"risk_flags\":[\"string\"],"
        "\"allow_enforcement\":false"
        "}.\n\n"
        "Rules:\n"
        "- Approve only low-risk, evidence-backed advisory candidates.\n"
        "- Reject malformed, unsupported, secret-risky, or dangerous candidates.\n"
        "- Use needs_human when evidence is ambiguous or the candidate could affect enforcement.\n"
        "- Never set allow_enforcement=true unless evidence explicitly supports it; Hermes will still require operator policy.\n\n"
        f"Candidate JSON:\n{json.dumps(evidence, indent=2, ensure_ascii=False)}\n"
    )


def call_learning_judge_model(judge_config: LearningJudgeConfig, prompt: str) -> str:
    from hermes_cli.curator_runtime import CuratorConfig, call_curator_model

    curator_config = CuratorConfig(
        enabled=judge_config.enabled,
        provider=judge_config.provider,
        model=judge_config.model,
        base_url=judge_config.base_url,
        mode="advisory",
        approval_required=True,
        timeout_seconds=judge_config.timeout_seconds,
        max_records=judge_config.max_candidates,
        min_score=judge_config.min_confidence,
    )
    return call_curator_model(curator_config, prompt)


def _fallback_decision_for_error(
    candidate_id: str,
    *,
    error: str,
    parse_error: bool,
    fail_closed: bool,
) -> LearningJudgeDecision:
    if parse_error and fail_closed:
        return LearningJudgeDecision(
            candidate_id=candidate_id,
            decision="reject",
            confidence=1.0,
            rationale=f"judge output failed strict schema validation: {error}",
            risk_flags=["malformed_judge_output"],
            allow_enforcement=False,
        )
    return LearningJudgeDecision(
        candidate_id=candidate_id,
        decision="needs_human",
        confidence=1.0,
        rationale=f"judge could not safely decide: {error}",
        risk_flags=["judge_unavailable"],
        allow_enforcement=False,
    )


def run_learning_judge(
    db: SessionDB,
    *,
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
    model_call: Optional[Callable[[LearningJudgeConfig, str], str]] = None,
) -> LearningJudgeRunResult:
    if config is None:
        config = load_config()
    judge_config = load_learning_judge_config(config)
    run_id = f"judge_{uuid.uuid4().hex[:16]}"
    job_id = None
    try:
        from hermes_cli.learning_jobs import record_learning_job

        job_id = record_learning_job(
            db,
            job_type="learning_judge",
            status="running",
            owner="judge",
            tenant_id=tenant_id,
            repo_id=repo_id,
            metrics={"run_id": run_id, "provider": judge_config.provider, "model": judge_config.model},
        ).id
    except Exception:
        job_id = None
    if not judge_config.enabled:
        result = LearningJudgeRunResult(
            run_id=run_id,
            status="disabled",
            candidates_scanned=0,
            candidates_judged=0,
            approved=0,
            rejected=0,
            needs_human=0,
            config=judge_config.to_dict(),
        )
        db.record_learning_run(
            run_id=run_id,
            tenant_id=tenant_id,
            repo_id=repo_id,
            status="disabled",
            metrics_json=result.to_dict(),
            notes="learning judge disabled",
        )
        try:
            from hermes_cli.learning_jobs import update_learning_job

            if job_id:
                update_learning_job(db, job_id, status="completed", metrics=result.to_dict())
        except Exception:
            pass
        return result

    caller = model_call or call_learning_judge_model
    candidates = db.list_meta_candidates(
        tenant_id=tenant_id,
        repo_id=repo_id,
        status="proposed",
        limit=judge_config.max_candidates,
    )

    approved = 0
    rejected = 0
    needs_human = 0
    results: List[LearningJudgeCandidateResult] = []
    errors: List[str] = []

    from hermes_cli.supervisor_memory import apply_learning_judge_decision

    for candidate in candidates:
        candidate_id = str(candidate.get("id") or "")
        prompt = build_learning_judge_prompt(candidate)
        error: Optional[str] = None
        try:
            raw = caller(judge_config, prompt)
            decision = parse_learning_judge_decision(raw, expected_candidate_id=candidate_id)
            if decision.decision == "approve" and decision.confidence < judge_config.min_confidence:
                decision = LearningJudgeDecision(
                    candidate_id=candidate_id,
                    decision="needs_human",
                    confidence=decision.confidence,
                    rationale=(
                        f"judge approval confidence {decision.confidence:.2f} "
                        f"is below required {judge_config.min_confidence:.2f}"
                    ),
                    risk_flags=[*decision.risk_flags, "low_judge_confidence"],
                    allow_enforcement=False,
                )
        except LearningJudgeParseError as exc:
            error = str(exc)
            decision = _fallback_decision_for_error(
                candidate_id,
                error=error,
                parse_error=True,
                fail_closed=judge_config.fail_closed,
            )
        except (TimeoutError, subprocess.TimeoutExpired) as exc:
            error = f"judge timeout: {exc}"
            decision = _fallback_decision_for_error(
                candidate_id,
                error=error,
                parse_error=False,
                fail_closed=judge_config.fail_closed,
            )
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            decision = _fallback_decision_for_error(
                candidate_id,
                error=error,
                parse_error=False,
                fail_closed=judge_config.fail_closed,
            )

        action = apply_learning_judge_decision(
            db,
            decision=decision,
            config=config,
            allow_enforcement=judge_config.allow_enforcement_approval,
        )
        if decision.decision == "approve":
            approved += 1
        elif decision.decision == "reject":
            rejected += 1
        else:
            needs_human += 1
        if error:
            errors.append(f"{candidate_id}: {error}")
        results.append(
            LearningJudgeCandidateResult(
                candidate_id=candidate_id,
                decision=decision.decision,
                status=action.status,
                confidence=decision.confidence,
                rationale=decision.rationale,
                risk_flags=decision.risk_flags,
                error=error,
            )
        )

    status = "completed" if not errors else "completed_with_errors"
    result = LearningJudgeRunResult(
        run_id=run_id,
        status=status,
        candidates_scanned=len(candidates),
        candidates_judged=len(results),
        approved=approved,
        rejected=rejected,
        needs_human=needs_human,
        results=results,
        errors=errors,
        config=judge_config.to_dict(),
    )
    db.record_learning_run(
        run_id=run_id,
        tenant_id=tenant_id,
        repo_id=repo_id,
        status=status,
        metrics_json=result.to_dict(),
        notes="learning judge completed",
    )
    try:
        from hermes_cli.learning_jobs import update_learning_job

        if job_id:
            update_learning_job(
                db,
                job_id,
                status="completed" if not errors else "failed",
                metrics=result.to_dict(),
                error={"errors": errors} if errors else None,
            )
    except Exception:
        pass
    return result
