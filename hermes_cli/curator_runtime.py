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
import time
import urllib.error
import urllib.request
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
    def approved_for_enforcement(self) -> bool:
        return self.status == "valid" and not self.errors

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["approved_for_enforcement"] = self.approved_for_enforcement
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


def call_curator_model(curator_config: CuratorConfig, prompt: str) -> str:
    provider = curator_config.provider.lower()
    if provider == "ollama":
        return _call_ollama(curator_config, prompt)
    if provider in {"custom", "openai-compatible", "openai_compatible", "cerebras"}:
        return _call_openai_compatible(curator_config, prompt)
    if provider in {"codex", "openai-codex", "deepseek"}:
        raise RuntimeError(
            f"curator provider '{curator_config.provider}' is configurable but "
            "does not have an in-process adapter yet; use provider=custom with "
            "an OpenAI-compatible base_url or run it via a worker integration."
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

    records = db.list_memory_records(
        tenant_id=tenant_id,
        repo_id=repo_id,
        kind="tool_routing_lesson",
        status="active",
        limit=curator_config.max_records,
    )
    candidates: list[CuratorPolicyCandidate] = []
    errors: list[str] = []
    caller = model_call or call_curator_model

    for record in records:
        score = float(record.get("score") or 0.0)
        if score < curator_config.min_score:
            continue
        prompt = build_command_repair_prompt(record)
        try:
            output = caller(curator_config, prompt)
        except (urllib.error.URLError, TimeoutError, RuntimeError, OSError) as exc:
            errors.append(f"{record.get('id')}: {type(exc).__name__}: {exc}")
            continue
        validation = validate_curator_output(output, record)
        policy_data = build_command_repair_policy_data(record, output)
        policy_data["validation"] = validation.to_dict()
        candidate_id = _stable_candidate_id(record, output)
        claim = _candidate_claim(record)
        status = "proposed"
        db.upsert_meta_candidate(
            candidate_id=candidate_id,
            kind="command_repair_policy",
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
                kind="command_repair_policy",
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
    )


def _candidate_claim(record: dict[str, Any]) -> str:
    payload = record.get("payload_json") if isinstance(record.get("payload_json"), dict) else {}
    failed = payload.get("failed_path") or "failed command path"
    working = payload.get("working_path") or "working command path"
    return f"Advisory command repair policy: prefer {working} after repeated {failed} failures"


def _stable_candidate_id(record: dict[str, Any], output: str) -> str:
    raw = "|".join(
        [
            "command_repair_policy",
            str(record.get("id") or ""),
            str(record.get("updated_at") or record.get("created_at") or ""),
            output[:120],
        ]
    )
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"curpol_{digest}"
