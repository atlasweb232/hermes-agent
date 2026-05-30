"""Configurable runtime curator for Hermes learning evidence.

The curator role is separate from the chat model and worker models. It reads
structured runtime evidence, asks a configured model for advisory synthesis, and
persists policy candidates that deterministic validators can later approve or
reject. Curator output is never enforcement by itself.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterable, Optional


CURATOR_POLICY_VERSION = "2026.05.16"


@dataclass
class CuratorConfig:
    enabled: bool = True
    provider: str = "ollama"
    model: str = "gemma2:2b"
    base_url: str = "http://127.0.0.1:11434"
    mode: str = "advisory"
    approval_required: bool = True
    timeout_seconds: float = 120.0
    max_records: int = 10
    min_score: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CuratorValidationResult:
    status: str
    warnings: list[dict[str, str]] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)

    @property
    def eligible_for_approval(self) -> bool:
        return self.status == "valid" and not self.errors

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["eligible_for_approval"] = self.eligible_for_approval
        data["approved_for_enforcement"] = False
        return data


@dataclass
class CuratorPolicyCandidate:
    candidate_id: str
    kind: str
    claim: str
    status: str
    score: float
    evidence: dict[str, Any]
    validation: CuratorValidationResult
    curator_output: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["validation"] = self.validation.to_dict()
        return data


@dataclass
class CuratorRunResult:
    status: str
    records_scanned: int
    candidates_created: int
    candidates: list[CuratorPolicyCandidate] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)
    precuration: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["candidates"] = [candidate.to_dict() for candidate in self.candidates]
        return data


def load_curator_config(config: Optional[dict[str, Any]]) -> CuratorConfig:
    supervisor = (config or {}).get("supervisor", {})
    if not isinstance(supervisor, dict):
        supervisor = {}
    raw = supervisor.get("curator", {})
    if not isinstance(raw, dict):
        raw = {}
    return CuratorConfig(
        enabled=bool(raw.get("enabled", True)),
        provider=str(raw.get("provider", "ollama") or "ollama"),
        model=str(raw.get("model", "gemma2:2b") or "gemma2:2b"),
        base_url=str(raw.get("base_url", "http://127.0.0.1:11434") or ""),
        mode=str(raw.get("mode", "advisory") or "advisory"),
        approval_required=bool(raw.get("approval_required", True)),
        timeout_seconds=float(raw.get("timeout_seconds", 120) or 120),
        max_records=int(raw.get("max_records", 10) or 10),
        min_score=float(raw.get("min_score", 0.5) or 0.5),
    )


def build_command_repair_prompt(record: dict[str, Any]) -> str:
    payload = record.get("payload_json") if isinstance(record.get("payload_json"), dict) else {}
    evidence = {
        "record_id": record.get("id"),
        "title": record.get("title"),
        "body": record.get("body"),
        "kind": record.get("kind"),
        "score": record.get("score"),
        "payload": payload,
    }
    return (
        "You are the Hermes offline curator. Produce an advisory command-repair "
        "policy candidate from the structured evidence below.\n\n"
        "Rules:\n"
        "- Do not invent facts not present in evidence.\n"
        "- Do not claim enforcement is already active.\n"
        "- Include evidence, confidence, and enforcement recommendation.\n"
        "- Keep output concise and auditable.\n\n"
        f"Policy version: {CURATOR_POLICY_VERSION}\n"
        f"Evidence JSON:\n{json.dumps(evidence, indent=2, ensure_ascii=False)}\n"
    )


def build_supervisor_failure_prompt(record: dict[str, Any]) -> str:
    payload = _bounded_supervisor_failure_payload(record)
    evidence = {
        "record_id": record.get("id"),
        "title": record.get("title"),
        "body": _redact_and_bound_text(str(record.get("body") or ""), max_chars=400),
        "kind": record.get("kind"),
        "score": record.get("score"),
        "payload": payload,
    }
    return (
        "You are the Hermes offline curator. Produce advisory-only recovery "
        "guidance from the structured supervisor runtime failure below.\n\n"
        "Rules:\n"
        "- Do not rewrite commands.\n"
        "- Do not enable enforcement or claim enforcement is active.\n"
        "- Do not approve memory automatically.\n"
        "- Preserve judge and operator approval gates.\n"
        "- Use only bounded, redacted evidence; never include raw logs or secrets.\n"
        "- Keep output concise and auditable.\n\n"
        f"Policy version: {CURATOR_POLICY_VERSION}\n"
        f"Evidence JSON:\n{json.dumps(evidence, indent=2, ensure_ascii=False)}\n"
    )


def call_curator_model(curator_config: CuratorConfig, prompt: str) -> str:
    provider = curator_config.provider.lower()
    if provider == "ollama":
        return _call_ollama(curator_config, prompt)
    if provider in {"custom", "openai-compatible", "openai_compatible", "cerebras"}:
        return _call_openai_compatible(curator_config, prompt)
    if provider in {"codex", "openai-codex"}:
        return _call_codex(curator_config, prompt)
    if provider == "deepseek":
        raise RuntimeError(
            "curator provider 'deepseek' should be configured as provider=custom "
            "with an OpenAI-compatible base_url."
        )
    raise RuntimeError(f"unsupported curator provider: {curator_config.provider}")


def _call_ollama(curator_config: CuratorConfig, prompt: str) -> str:
    base_url = curator_config.base_url.rstrip("/")
    body = {
        "model": curator_config.model,
        "prompt": prompt,
        "stream": False,
    }
    request = urllib.request.Request(
        f"{base_url}/api/generate",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=curator_config.timeout_seconds) as response:
        data = json.loads(response.read().decode("utf-8"))
    return str(data.get("response") or "").strip()


def _call_openai_compatible(curator_config: CuratorConfig, prompt: str) -> str:
    base_url = curator_config.base_url.rstrip("/")
    if not base_url:
        raise RuntimeError("custom curator provider requires supervisor.curator.base_url")
    body = {
        "model": curator_config.model,
        "messages": [
            {"role": "system", "content": "You are a careful advisory curator."},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
    }
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=curator_config.timeout_seconds) as response:
        data = json.loads(response.read().decode("utf-8"))
    choices = data.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") if isinstance(choices[0], dict) else {}
    return str((message or {}).get("content") or "").strip()


def _call_codex(
    curator_config: CuratorConfig,
    prompt: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> str:
    """Run Codex as an external advisory curator worker.

    Codex is launched in read-only, non-interactive mode. It receives only the
    structured curator prompt on stdin and writes the final response to a temp
    file so logs/events on stdout do not contaminate the candidate text.
    """
    with tempfile.NamedTemporaryFile("w+", encoding="utf-8", delete=False) as tmp:
        output_path = Path(tmp.name)
    try:
        cmd = [
            "codex",
            "exec",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--ignore-rules",
            "--output-last-message",
            str(output_path),
        ]
        if curator_config.model and curator_config.model not in {"codex", "default", "auto"}:
            cmd.extend(["--model", curator_config.model])
        cmd.append("-")
        completed = runner(
            cmd,
            input=prompt,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=curator_config.timeout_seconds,
            check=False,
        )
        output = ""
        if output_path.exists():
            output = output_path.read_text(encoding="utf-8").strip()
        if completed.returncode != 0:
            stderr = (completed.stderr or "").strip()
            stdout = (completed.stdout or "").strip()
            detail = stderr or stdout or f"exit code {completed.returncode}"
            raise RuntimeError(f"codex curator failed: {detail[:1000]}")
        return output or (completed.stdout or "").strip()
    finally:
        try:
            output_path.unlink(missing_ok=True)
        except Exception:
            pass


def validate_curator_output(output: str, record: dict[str, Any]) -> CuratorValidationResult:
    warnings: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    payload = record.get("payload_json") if isinstance(record.get("payload_json"), dict) else {}
    evidence_text = json.dumps(payload, ensure_ascii=False).lower()
    output_text = str(output or "").lower()

    unsupported_terms = {
        "docker": "Docker was not present in the runtime lesson evidence.",
        "gpu": "GPU was not present in the runtime lesson evidence.",
        "kubernetes": "Kubernetes was not present in the runtime lesson evidence.",
    }
    for term, reason in unsupported_terms.items():
        if term in output_text and term not in evidence_text:
            warnings.append(
                {
                    "code": "unsupported_claim_warning",
                    "claim": term,
                    "reason": reason,
                }
            )

    if re.search(r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*\S+", str(output or "")):
        errors.append(
            {
                "code": "secret_like_output",
                "reason": "Curator output appears to contain a secret-like assignment.",
            }
        )

    if "worker-router claude" in evidence_text and "claude" not in output_text:
        warnings.append(
            {
                "code": "missing_success_path",
                "reason": "Output does not mention the observed successful direct Claude path.",
            }
        )
    if re.search(r"(?i)\b(for all user requests|mandate|must always|always use)\b", str(output or "")):
        warnings.append(
            {
                "code": "overbroad_enforcement_language",
                "reason": "Curator output uses broad enforcement language; candidate must remain advisory until a bounded policy is approved.",
            }
        )

    status = "invalid" if errors else ("warning" if warnings else "valid")
    return CuratorValidationResult(status=status, warnings=warnings, errors=errors)


def build_command_repair_policy_data(record: dict[str, Any], output: str) -> dict[str, Any]:
    payload = record.get("payload_json") if isinstance(record.get("payload_json"), dict) else {}
    return {
        "policy_version": CURATOR_POLICY_VERSION,
        "policy_type": "command_repair",
        "mode": "advisory",
        "source_record_id": record.get("id"),
        "failed_path": payload.get("failed_path"),
        "working_path": payload.get("working_path"),
        "failure_count": payload.get("failure_count"),
        "failed_commands": payload.get("failed_commands") or [],
        "working_command": payload.get("working_command"),
        "curator_output": output,
        "created_at": time.time(),
    }


def _redact_and_bound_text(value: Any, *, max_chars: int) -> str:
    """Strict-redact and length-bound a value before it enters a curator payload.

    Delegates redaction to the shared
    :func:`hermes_cli.memory_redaction.redact_for_persistence` so curator
    persistence uses the same strict (full-erase + canonical) redactor as the
    rest of the learning pipeline instead of a local regex.
    """
    from hermes_cli.memory_redaction import redact_for_persistence

    return redact_for_persistence(value, max_chars=max_chars)


def _bounded_supervisor_failure_payload(record: dict[str, Any]) -> dict[str, Any]:
    payload = record.get("payload_json") if isinstance(record.get("payload_json"), dict) else {}
    validation_mismatch = payload.get("validation_mismatch")
    if not isinstance(validation_mismatch, dict):
        validation_mismatch = {}
    bounded_mismatch = {
        _redact_and_bound_text(key, max_chars=80): _redact_and_bound_text(value, max_chars=220)
        for key, value in list(validation_mismatch.items())[:12]
    }
    evidence_refs = payload.get("evidence_refs") if isinstance(payload.get("evidence_refs"), list) else []
    return {
        "detector": _redact_and_bound_text(payload.get("detector"), max_chars=120),
        "failure_type": _redact_and_bound_text(payload.get("failure_type"), max_chars=80),
        "task_id": _redact_and_bound_text(payload.get("task_id") or record.get("task_id"), max_chars=120),
        "worker_id": _redact_and_bound_text(payload.get("worker_id"), max_chars=120),
        "route": _redact_and_bound_text(payload.get("route"), max_chars=220),
        "command_family": _redact_and_bound_text(payload.get("command_family"), max_chars=120),
        "status": _redact_and_bound_text(payload.get("status"), max_chars=80),
        "allocation_id": _redact_and_bound_text(payload.get("allocation_id"), max_chars=120),
        "attempt_id": _redact_and_bound_text(payload.get("attempt_id"), max_chars=120),
        "evidence_refs": [
            _redact_and_bound_text(ref, max_chars=220)
            for ref in evidence_refs[:10]
            if str(ref or "").strip()
        ],
        "validation_mismatch": bounded_mismatch,
        "output_excerpt": _redact_and_bound_text(payload.get("output_excerpt"), max_chars=360),
        "error_excerpt": _redact_and_bound_text(payload.get("error_excerpt"), max_chars=360),
        "route_substitution": bool(payload.get("route_substitution")),
        "requires_judge": bool(payload.get("requires_judge", True)),
        "operator_approval_required": bool(payload.get("operator_approval_required", True)),
    }


def classify_supervisor_failure_types(record: dict[str, Any]) -> list[str]:
    payload = record.get("payload_json") if isinstance(record.get("payload_json"), dict) else {}
    status = str(payload.get("status") or "").strip().lower()
    failure_type = str(payload.get("failure_type") or "").strip().lower()
    validation_mismatch = payload.get("validation_mismatch")
    mismatch = validation_mismatch if isinstance(validation_mismatch, dict) else {}
    text = " ".join(
        str(part or "").lower()
        for part in [
            status,
            failure_type,
            payload.get("route"),
            payload.get("error_excerpt"),
            payload.get("output_excerpt"),
            json.dumps(mismatch, sort_keys=True),
        ]
    )
    classes: list[str] = []

    def add(label: str) -> None:
        if label not in classes:
            classes.append(label)

    if status == "empty_output" or "empty output" in text:
        add("empty_output")
    if status in {"timeout", "timed_out"} or "timed out" in text or "timeout" in text:
        add("timeout")
    if status in {"false_completion", "completion_blocked_hallucination"} or re.search(
        r"\b(false completion|claimed completion)\b",
        text,
    ):
        add("false completion")
    validation_status = str(mismatch.get("validation_status") or "").strip().lower()
    if mismatch and (validation_status not in {"", "passed", "success", "ok"} or "validation" in text):
        add("validation mismatch")
    if payload.get("route_substitution") or (
        mismatch.get("expected_route") and mismatch.get("actual_route")
    ):
        add("route substitution")
    if status in {"auth_failed", "auth_failure"} or re.search(r"\b(auth|unauthorized|forbidden)\b", text):
        add("auth failure")
    if status == "network_degraded" or re.search(r"\b(network|connection|dns|degraded)\b", text):
        add("network degradation")
    if status == "quota_exhausted" or re.search(r"\b(quota|rate limit|429)\b", text):
        add("quota exhaustion")
    if not classes:
        add("validation mismatch" if mismatch else "timeout" if "timed" in text else "empty_output")
    return classes


def _supervisor_failure_candidate_kind(record: dict[str, Any], classifications: list[str]) -> str:
    payload = record.get("payload_json") if isinstance(record.get("payload_json"), dict) else {}
    failure_type = str(payload.get("failure_type") or "").lower()
    detector = str(payload.get("detector") or "").lower()
    labels = set(classifications)
    if labels & {"quota exhaustion", "auth failure", "network degradation"}:
        return "worker_health_rule"
    if "allocator" in failure_type or "allocator" in detector:
        return "worker_health_rule"
    if "route substitution" in labels:
        return "routing_hint"
    if labels & {"empty_output", "timeout"}:
        return "recovery_hint"
    if labels <= {"validation mismatch", "false completion"} or "false completion" in labels:
        return "validation_rule"
    return "recovery_hint"


def build_supervisor_failure_policy_data(
    record: dict[str, Any],
    output: str,
    validation: CuratorValidationResult,
) -> dict[str, Any]:
    classifications = classify_supervisor_failure_types(record)
    return {
        "policy_version": CURATOR_POLICY_VERSION,
        "policy_type": "supervisor_runtime_failure_advisory",
        "mode": "advisory",
        "source_record_id": record.get("id"),
        "source_record_kind": "supervisor_runtime_failure",
        "failure_classifications": classifications,
        "payload": _bounded_supervisor_failure_payload(record),
        "curator_output": _redact_and_bound_text(output, max_chars=1200),
        "validation": validation.to_dict(),
        "requires_judge": True,
        "operator_approval_required": True,
        "approved_for_enforcement": False,
        "created_at": time.time(),
    }


def run_curator_policy_pass(
    db: Any,
    *,
    config: Optional[dict[str, Any]] = None,
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    model_call: Optional[Callable[[CuratorConfig, str], str]] = None,
) -> CuratorRunResult:
    curator_config = load_curator_config(config)
    if not curator_config.enabled:
        return CuratorRunResult(
            status="disabled",
            records_scanned=0,
            candidates_created=0,
            config=curator_config.to_dict(),
        )

    tool_records = db.list_memory_records(
        tenant_id=tenant_id,
        repo_id=repo_id,
        kind="tool_routing_lesson",
        status="active",
        limit=curator_config.max_records,
    )
    failure_records = db.list_memory_records(
        tenant_id=tenant_id,
        repo_id=repo_id,
        kind="supervisor_runtime_failure",
        status="active",
        limit=curator_config.max_records,
    )
    records = [*tool_records, *failure_records]
    candidates: list[CuratorPolicyCandidate] = []
    errors: list[str] = []
    precuration_metrics: dict[str, Any] = {
        "enabled": True,
        "records_skipped": 0,
        "global_lesson_hit": 0,
        "global_lesson_near_hit": 0,
        "global_lesson_miss": 0,
        "decisions": [],
    }
    caller = model_call or call_curator_model

    for record in records:
        score = float(record.get("score") or 0.0)
        if score < curator_config.min_score:
            continue
        is_supervisor_failure = record.get("kind") == "supervisor_runtime_failure"
        if not is_supervisor_failure:
            precuration = _run_record_precuration(
                db,
                record,
                config=config,
                tenant_id=tenant_id,
                repo_id=repo_id,
            )
            if precuration is not None:
                decision = precuration.get("decision") or {}
                metric = str(decision.get("metric") or "")
                if metric:
                    precuration_metrics[metric] = int(precuration_metrics.get(metric, 0)) + 1
                precuration_metrics["decisions"].append(precuration)
                if decision.get("should_run_expensive_curator") is False:
                    precuration_metrics["records_skipped"] += 1
                    continue
        prompt = build_supervisor_failure_prompt(record) if is_supervisor_failure else build_command_repair_prompt(record)
        try:
            output = caller(curator_config, prompt)
        except (urllib.error.URLError, TimeoutError, RuntimeError, OSError) as exc:
            errors.append(f"{record.get('id')}: {type(exc).__name__}: {exc}")
            continue
        validation = validate_curator_output(output, record)
        if is_supervisor_failure:
            classifications = classify_supervisor_failure_types(record)
            kind = _supervisor_failure_candidate_kind(record, classifications)
            policy_data = build_supervisor_failure_policy_data(record, output, validation)
            candidate_id = _stable_supervisor_failure_candidate_id(record, kind)
            claim = _supervisor_failure_candidate_claim(record, kind, classifications)
        else:
            kind = "command_repair_policy"
            policy_data = build_command_repair_policy_data(record, output)
            policy_data["validation"] = validation.to_dict()
            candidate_id = _stable_candidate_id(record, output)
            claim = _candidate_claim(record)
        status = "proposed"
        db.upsert_meta_candidate(
            candidate_id=candidate_id,
            kind=kind,
            claim=claim,
            evidence_json=policy_data,
            score=score,
            status=status,
            tenant_id=tenant_id,
            repo_id=repo_id,
        )
        candidates.append(
            CuratorPolicyCandidate(
                candidate_id=candidate_id,
                kind=kind,
                claim=claim,
                status=status,
                score=score,
                evidence=policy_data,
                validation=validation,
                curator_output=output,
            )
        )

    return CuratorRunResult(
        status="completed" if not errors else "degraded",
        records_scanned=len(records),
        candidates_created=len(candidates),
        candidates=candidates,
        errors=errors,
        config=curator_config.to_dict(),
        precuration=precuration_metrics,
    )


def _run_record_precuration(
    db: Any,
    record: dict[str, Any],
    *,
    config: Optional[dict[str, Any]],
    tenant_id: Optional[str],
    repo_id: Optional[str],
) -> Optional[dict[str, Any]]:
    try:
        from hermes_cli.global_memory import run_persisted_global_precuration
    except Exception:
        return None
    payload = record.get("payload_json") if isinstance(record.get("payload_json"), dict) else {}
    failed_path = str(payload.get("failed_path") or "")
    working_path = str(payload.get("working_path") or "")
    event = {
        "event_id": str(record.get("id") or ""),
        "tenant_id": tenant_id or record.get("tenant_id"),
        "repo_id": repo_id or record.get("repo_id"),
        "task_type": "worker_routing",
        "tool": failed_path.split()[0] if failed_path else "",
        "worker_kind": failed_path,
        "failure_signature": str(payload.get("failure_signature") or (f"path:{failed_path}" if failed_path else "")),
        "success_signature": str(payload.get("success_signature") or (f"path:{working_path}" if working_path else "")),
        "scope_signature": str(payload.get("scope_signature") or ""),
        "evidence_signature": str(payload.get("evidence_signature") or record.get("evidence_sha256") or record.get("evidence_uri") or ""),
        "normalized_text": " ".join(
            part
            for part in [
                str(record.get("title") or ""),
                str(record.get("body") or ""),
                failed_path,
                working_path,
            ]
            if part
        ),
    }
    try:
        result = run_persisted_global_precuration(
            db,
            event,
            config=config,
            limit=3,
            record_feedback=True,
        )
        return result.to_dict()
    except Exception as exc:
        return {"status": "error", "error": str(exc), "record_id": record.get("id")}


def _candidate_claim(record: dict[str, Any]) -> str:
    payload = record.get("payload_json") if isinstance(record.get("payload_json"), dict) else {}
    failed = payload.get("failed_path") or "failed command path"
    working = payload.get("working_path") or "working command path"
    return f"Advisory command repair policy: prefer {working} after repeated {failed} failures"


def _stable_candidate_id(record: dict[str, Any], output: str) -> str:
    raw = "|".join(
        [
            "command_repair_policy",
            CURATOR_POLICY_VERSION,
            str(record.get("id") or ""),
        ]
    )
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"curpol_{digest}"


def _supervisor_failure_candidate_claim(record: dict[str, Any], kind: str, classifications: list[str]) -> str:
    payload = record.get("payload_json") if isinstance(record.get("payload_json"), dict) else {}
    worker = payload.get("worker_id") or payload.get("command_family") or "worker"
    task_id = payload.get("task_id") or record.get("task_id") or "task"
    labels = ", ".join(classifications)
    if kind == "worker_health_rule":
        return f"Advisory worker health rule for {worker} after {labels} in {task_id}"
    if kind == "routing_hint":
        return f"Advisory routing hint after {labels} in {task_id}"
    if kind == "validation_rule":
        return f"Advisory validation rule after {labels} in {task_id}"
    return f"Advisory recovery hint after {labels} in {task_id}"


def _stable_supervisor_failure_candidate_id(record: dict[str, Any], kind: str) -> str:
    raw = "|".join(
        [
            kind,
            "supervisor_runtime_failure_advisory",
            CURATOR_POLICY_VERSION,
            str(record.get("id") or ""),
        ]
    )
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"curadv_{digest}"
