"""Deterministic completion gates for delegated repository work.

The gate is deliberately tool-driven: a worker may claim success, but Hermes
only allows a successful final report when repo checks produce clean evidence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import json
import os
import re
import shlex
import subprocess
from typing import Any, Iterable


SUCCESS_WORDS = (
    "complete",
    "completed",
    "done",
    "merged",
    "resolved",
    "passed",
    "committed",
    "succeeded",
    "success",
)


@dataclass
class CheckResult:
    name: str
    passed: bool
    command: list[str]
    stdout: str = ""
    stderr: str = ""
    returncode: int | None = None
    skipped: bool = False
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CompletionGateResult:
    enabled: bool
    status: str
    repo_path: str | None = None
    checks: list[CheckResult] = field(default_factory=list)
    reason: str = ""

    @property
    def passed(self) -> bool:
        return self.status == "passed"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["passed"] = self.passed
        return data


def load_completion_gate_config(config: dict[str, Any] | None) -> dict[str, Any]:
    supervisor = (config or {}).get("supervisor", {})
    if not isinstance(supervisor, dict):
        supervisor = {}
    gate = supervisor.get("completion_gate", {})
    if not isinstance(gate, dict):
        gate = {}
    return {
        "enabled": bool(gate.get("enabled", True)),
        "fail_on_missing_repo": bool(gate.get("fail_on_missing_repo", False)),
        "run_after_delegate_task": bool(gate.get("run_after_delegate_task", True)),
        "required_checks": list(
            gate.get(
                "required_checks",
                ["git_unmerged_paths", "conflict_markers", "diff_check"],
            )
            or []
        ),
        "build_commands": list(gate.get("build_commands", []) or []),
        # Held-out (worker-unseen) checks: run post-hoc by the supervisor/curator,
        # never surfaced to the worker. This is the train/test split that makes the
        # learning signal resistant to Goodharting the visible build_commands.
        "held_out_commands": list(gate.get("held_out_commands", []) or []),
        "max_output_chars": int(gate.get("max_output_chars", 8000) or 8000),
    }


def run_completion_gate(
    *,
    repo_path: str | os.PathLike[str] | None,
    config: dict[str, Any] | None = None,
) -> CompletionGateResult:
    gate_cfg = load_completion_gate_config(config)
    if not gate_cfg["enabled"]:
        return CompletionGateResult(enabled=False, status="skipped", reason="disabled")

    if not repo_path:
        status = "blocked" if gate_cfg["fail_on_missing_repo"] else "skipped"
        return CompletionGateResult(
            enabled=True,
            status=status,
            reason="no repository path detected",
        )

    repo = Path(repo_path).expanduser().resolve()
    if not (repo / ".git").exists():
        status = "blocked" if gate_cfg["fail_on_missing_repo"] else "skipped"
        return CompletionGateResult(
            enabled=True,
            status=status,
            repo_path=str(repo),
            reason="path is not a git repository",
        )

    checks: list[CheckResult] = []
    required = set(str(c) for c in gate_cfg["required_checks"])
    max_chars = gate_cfg["max_output_chars"]

    if "git_unmerged_paths" in required:
        checks.append(_check_git_unmerged_paths(repo, max_chars=max_chars))
    if "conflict_markers" in required:
        checks.append(_check_conflict_markers(repo, max_chars=max_chars))
    if "diff_check" in required:
        checks.append(_check_diff_check(repo, max_chars=max_chars))
    if "commit_present" in required:
        checks.append(_check_commit_present(repo, max_chars=max_chars))

    for command in gate_cfg["build_commands"]:
        checks.append(_check_build_command(repo, command, max_chars=max_chars))

    failed = [check for check in checks if not check.skipped and not check.passed]
    status = "passed" if not failed else "blocked"
    reason = "" if not failed else "one or more deterministic checks failed"
    return CompletionGateResult(
        enabled=True,
        status=status,
        repo_path=str(repo),
        checks=checks,
        reason=reason,
    )


def run_held_out_gate(
    *,
    repo_path: str | os.PathLike[str] | None,
    config: dict[str, Any] | None = None,
) -> CompletionGateResult:
    """Run the held-out (worker-unseen) check set against an already-finished repo.

    This is intentionally NOT part of ``run_completion_gate`` / the delegate payload:
    the worker must never see these commands, or the train/test split collapses. The
    supervisor/curator runs this after the worker reports done. The outcome is what
    legitimately licenses ``held_out=True`` on a verification record — a worker that
    overfit the visible ``build_commands`` still has to satisfy unseen checks here.

    Returns ``status="skipped"`` when no ``held_out_commands`` are configured, so a
    caller can never mint a held-out verification without checks having actually run.
    """
    gate_cfg = load_completion_gate_config(config)
    commands = gate_cfg["held_out_commands"]
    if not commands:
        return CompletionGateResult(
            enabled=True, status="skipped", reason="no held_out_commands configured"
        )
    if not repo_path:
        return CompletionGateResult(
            enabled=True, status="skipped", reason="no repository path detected"
        )
    repo = Path(repo_path).expanduser().resolve()
    if not (repo / ".git").exists():
        return CompletionGateResult(
            enabled=True, status="skipped", repo_path=str(repo),
            reason="path is not a git repository",
        )

    max_chars = gate_cfg["max_output_chars"]
    checks: list[CheckResult] = []
    for command in commands:
        check = _check_build_command(repo, command, max_chars=max_chars)
        check.name = "held_out"
        checks.append(check)

    failed = [c for c in checks if not c.skipped and not c.passed]
    status = "passed" if not failed else "blocked"
    reason = "" if not failed else "one or more held-out checks failed"
    return CompletionGateResult(
        enabled=True, status=status, repo_path=str(repo), checks=checks, reason=reason,
    )


def append_gate_to_delegate_payload(
    delegate_payload: str,
    gate: CompletionGateResult,
) -> str:
    """Attach gate evidence to a delegate_task JSON result.

    If the payload is not JSON, keep it intact and wrap it. This keeps the tool
    result machine-readable for the supervisor and prevents worker prose from
    being treated as authoritative.
    """
    try:
        payload = json.loads(delegate_payload)
    except Exception:
        payload = {"raw_delegate_result": delegate_payload}

    if not isinstance(payload, dict):
        payload = {"delegate_result": payload}

    gate_dict = gate.to_dict()
    payload["completion_gate"] = gate_dict
    if gate.enabled and not gate.passed and gate.status != "skipped":
        payload["status"] = "blocked"
        payload["error"] = "completion gate blocked success"
        for entry in payload.get("results") or []:
            if isinstance(entry, dict) and entry.get("status") == "completed":
                entry["worker_status"] = entry["status"]
                entry["status"] = "blocked"
                entry["error"] = "completion gate blocked worker success claim"
                entry["completion_gate"] = gate_dict

    return json.dumps(payload, ensure_ascii=False)


def enforce_final_response_gate(
    final_response: str,
    gate: CompletionGateResult | dict[str, Any] | None,
) -> str:
    """Force a blocked final response when the latest gate failed."""
    gate_obj = _coerce_gate(gate)
    if gate_obj is None or not gate_obj.enabled or gate_obj.status in {"passed", "skipped"}:
        return final_response

    evidence_lines = []
    for check in gate_obj.checks:
        if check.skipped or check.passed:
            continue
        detail = (check.stdout or check.stderr or check.reason or "").strip()
        if detail:
            detail = detail.splitlines()[0][:240]
            evidence_lines.append(f"- {check.name}: failed ({detail})")
        else:
            evidence_lines.append(f"- {check.name}: failed")

    evidence = "\n".join(evidence_lines) or f"- reason: {gate_obj.reason or gate_obj.status}"
    original = final_response.strip()
    if _contains_success_claim(original):
        original = f"\n\nWorker narrative was suppressed because it claimed success without passing the gate.\n\nOriginal response:\n{original}"
    elif original:
        original = f"\n\nWorker narrative:\n{original}"

    repo = gate_obj.repo_path or "unknown"
    return (
        "Blocked: deterministic completion gate did not pass.\n\n"
        f"Repository: {repo}\n"
        "Failed checks:\n"
        f"{evidence}"
        f"{original}"
    )


def resolve_repo_path_from_texts(
    texts: Iterable[str | None],
    *,
    cwd: str | os.PathLike[str] | None = None,
) -> str | None:
    """Best-effort repo path extraction from task text and current cwd."""
    for text in texts:
        if not text:
            continue
        for match in re.finditer(r"(?P<path>/(?:[^\s'\"`:,;])+)", str(text)):
            candidate = match.group("path").rstrip(").]")
            path = Path(candidate).expanduser()
            if (path / ".git").exists():
                return str(path.resolve())

    if cwd:
        path = Path(cwd).expanduser()
        if (path / ".git").exists():
            return str(path.resolve())
    return None


def _check_git_unmerged_paths(repo: Path, *, max_chars: int) -> CheckResult:
    result = _run(["git", "ls-files", "-u"], repo, max_chars=max_chars)
    result.name = "git_unmerged_paths"
    result.passed = result.returncode == 0 and not result.stdout.strip()
    return result


def _check_conflict_markers(repo: Path, *, max_chars: int) -> CheckResult:
    if _command_exists("rg"):
        command = ["rg", "-n", r"<<<<<<<|=======|>>>>>>>", "."]
        result = _run(command, repo, max_chars=max_chars)
        result.name = "conflict_markers"
        result.passed = result.returncode == 1
        return result

    command = ["git", "grep", "-n", r"<<<<<<<\|=======\|>>>>>>>"]
    result = _run(command, repo, max_chars=max_chars)
    result.name = "conflict_markers"
    result.passed = result.returncode == 1
    return result


def _check_diff_check(repo: Path, *, max_chars: int) -> CheckResult:
    result = _run(["git", "diff", "--check"], repo, max_chars=max_chars)
    result.name = "diff_check"
    result.passed = result.returncode == 0
    return result


def _check_commit_present(repo: Path, *, max_chars: int) -> CheckResult:
    result = _run(["git", "rev-parse", "--verify", "HEAD"], repo, max_chars=max_chars)
    result.name = "commit_present"
    result.passed = result.returncode == 0 and bool(result.stdout.strip())
    return result


def _check_build_command(repo: Path, command: Any, *, max_chars: int) -> CheckResult:
    if isinstance(command, str):
        argv = shlex.split(command)
    elif isinstance(command, list):
        argv = [str(part) for part in command]
    else:
        return CheckResult(
            name="build",
            passed=False,
            command=[],
            reason=f"invalid build command: {command!r}",
        )
    result = _run(argv, repo, max_chars=max_chars)
    result.name = "build"
    result.passed = result.returncode == 0
    return result


def _run(command: list[str], cwd: Path, *, max_chars: int) -> CheckResult:
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
            check=False,
        )
        return CheckResult(
            name=command[0] if command else "command",
            passed=False,
            command=command,
            stdout=_tail(completed.stdout, max_chars),
            stderr=_tail(completed.stderr, max_chars),
            returncode=completed.returncode,
        )
    except FileNotFoundError as exc:
        return CheckResult(
            name=command[0] if command else "command",
            passed=False,
            command=command,
            stderr=str(exc),
            returncode=127,
        )
    except subprocess.TimeoutExpired as exc:
        return CheckResult(
            name=command[0] if command else "command",
            passed=False,
            command=command,
            stdout=_tail(exc.stdout or "", max_chars),
            stderr=_tail(exc.stderr or "", max_chars),
            returncode=None,
            reason="timeout",
        )


def _tail(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def _command_exists(command: str) -> bool:
    paths = os.environ.get("PATH", "").split(os.pathsep)
    return any((Path(path) / command).exists() for path in paths if path)


def _contains_success_claim(text: str) -> bool:
    lowered = text.lower()
    return any(re.search(rf"\b{re.escape(word)}\b", lowered) for word in SUCCESS_WORDS)


def _coerce_gate(gate: CompletionGateResult | dict[str, Any] | None) -> CompletionGateResult | None:
    if gate is None:
        return None
    if isinstance(gate, CompletionGateResult):
        return gate
    if not isinstance(gate, dict):
        return None
    checks = []
    for raw in gate.get("checks") or []:
        if isinstance(raw, dict):
            checks.append(CheckResult(**{k: raw.get(k) for k in CheckResult.__dataclass_fields__}))
    return CompletionGateResult(
        enabled=bool(gate.get("enabled", True)),
        status=str(gate.get("status") or ""),
        repo_path=gate.get("repo_path"),
        checks=checks,
        reason=str(gate.get("reason") or ""),
    )
