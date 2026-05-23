"""Release-readiness report builder for runtime-learning closure.

The report is intentionally markdown-first because the current release gate is
reviewed by operators in git. Inputs are already redacted CLI/API payloads from
the production smoke, runtime impact, sidecar readiness, model-role doctor, and
cost telemetry surfaces.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from typing import Any, Iterable, Mapping

from hermes_cli.redaction_guard import assert_redacted, redact_value


@dataclass(frozen=True)
class CommandEvidence:
    command: str
    status: str
    summary: str


@dataclass(frozen=True)
class ReleaseReadinessReport:
    branch: str
    head: str
    validation_date: str
    production_smoke: Mapping[str, Any]
    runtime_impact: Mapping[str, Any]
    sidecar_status: Mapping[str, Any]
    model_role_doctor: Mapping[str, Any]
    cost_status: Mapping[str, Any]
    command_evidence: tuple[CommandEvidence, ...] = field(default_factory=tuple)
    known_blockers: tuple[str, ...] = field(default_factory=tuple)


def utc_date() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def build_release_readiness_markdown(report: ReleaseReadinessReport) -> str:
    payload = redact_value(
        {
            "production_smoke": report.production_smoke,
            "runtime_impact": report.runtime_impact,
            "sidecar_status": report.sidecar_status,
            "model_role_doctor": report.model_role_doctor,
            "cost_status": report.cost_status,
            "command_evidence": [item.__dict__ for item in report.command_evidence],
            "known_blockers": list(report.known_blockers),
        }
    )
    assert_redacted(payload)

    smoke = dict(payload["production_smoke"])
    impact = dict(payload["runtime_impact"])
    sidecars = dict(payload["sidecar_status"])
    doctor = dict(payload["model_role_doctor"])
    costs = dict(payload["cost_status"])

    gates = list(smoke.get("gates") or [])
    passed_gates = sum(1 for gate in gates if gate.get("status") == "passed")
    failed_gates = sum(1 for gate in gates if gate.get("status") == "failed")
    sidecar_items = list(sidecars.get("items") or sidecars.get("sidecars") or sidecars.get("checks") or [])
    runtime_foreground = dict(impact.get("foreground") or {})
    latency = dict(impact.get("latency_attribution") or {})
    context = dict(impact.get("context_attribution") or {})
    cost_attribution = dict(impact.get("cost_attribution") or {})
    cost_totals = dict(costs.get("totals") or costs)
    known_blockers = list(payload["known_blockers"])
    if not known_blockers:
        known_blockers = ["None for deterministic production-closure smoke."]
    has_real_blockers = known_blockers != ["None for deterministic production-closure smoke."]

    lines: list[str] = [
        "# Runtime Learning Release Readiness",
        "",
        f"Branch: `{report.branch}`",
        "",
        f"Validation date: {report.validation_date}",
        "",
        f"Validated HEAD: `{report.head}`",
        "",
        "## Summary",
        "",
        (
            "Production-closure validation "
            f"{'passed' if smoke.get('status') == 'passed' and failed_gates == 0 and not has_real_blockers else 'requires review'} "
            "for the runtime-learning branch."
        ),
        "",
        "| Gate Group | Status | Evidence |",
        "| --- | --- | --- |",
        _row("production smoke", str(smoke.get("status") or "unknown"), f"{passed_gates} passed, {failed_gates} failed"),
        _row("runtime impact", str(impact.get("kind") or "unknown"), _impact_summary(runtime_foreground, latency)),
        _row("sidecar readiness", str(sidecars.get("status") or "unknown"), f"{len(sidecar_items)} sidecar checks"),
        _row("model-role doctor", str(doctor.get("status") or "unknown"), _doctor_summary(doctor)),
        _row("cost/context", str(costs.get("status") or "reported"), _cost_summary(cost_totals, cost_attribution, context)),
        "",
        "## Production Closure Gates",
        "",
        "| Gate | Status | Details |",
        "| --- | --- | --- |",
    ]
    for gate in gates:
        details = ", ".join(
            f"{key}={_compact(value)}"
            for key, value in gate.items()
            if key not in {"name", "status"}
        )
        lines.append(_row(str(gate.get("name") or "unknown"), str(gate.get("status") or "unknown"), details or "-"))

    lines.extend(
        [
            "",
            "## Runtime Impact Evidence",
            "",
            "| Metric | Value |",
            "| --- | --- |",
            _row("foreground sidecar blocking", _compact(runtime_foreground.get("foreground_sidecar_blocking")), "must remain false"),
            _row("raw worker updates in context", _compact(runtime_foreground.get("raw_worker_updates_in_context")), "must remain false"),
            _row("raw logs loaded", _compact(impact.get("raw_logs_loaded")), "must remain false"),
            _row("raw transcripts loaded", _compact(impact.get("raw_transcripts_loaded")), "must remain false"),
            _row("foreground latency ms", _compact(latency.get("foreground_ms")), "task-visible latency"),
            _row("background sidecar ms", _compact(latency.get("background_sidecar_ms")), "async latency attribution"),
            _row("context admitted tokens", _compact(context.get("context_admitted_tokens")), "supervisor context budget"),
            _row("offloaded worker events", _compact(context.get("offloaded_worker_events")), "stored as refs"),
            "",
            "## Sidecar Status",
            "",
            "| Sidecar | Status | Mode | Non-blocking | Details |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    if sidecar_items:
        for item in sidecar_items:
            lines.append(
                _row(
                    str(item.get("name") or item.get("sidecar") or item.get("role") or "unknown"),
                    str(item.get("status") or "unknown"),
                    str(item.get("mode") or sidecars.get("mode") or "unknown"),
                    _compact(item.get("foreground_blocking", sidecars.get("foreground_blocking"))),
                    _sidecar_details(item),
                )
            )
    else:
        lines.append(_row("none", "not_reported", "-", "-", "sidecar status payload had no per-sidecar rows"))

    lines.extend(
        [
            "",
            "## Cost And Context Totals",
            "",
            "| Metric | Value |",
            "| --- | --- |",
            _row("estimated cost usd", _compact(_first_present(cost_totals, cost_attribution, "total_estimated_cost_usd", "estimated_cost_usd")), ""),
            _row("prompt/input tokens", _compact(_first_present(cost_totals, cost_attribution, "total_prompt_tokens", "prompt_tokens", "input_tokens")), ""),
            _row("completion/output tokens", _compact(_first_present(cost_totals, cost_attribution, "total_completion_tokens", "completion_tokens", "output_tokens")), ""),
            _row("run count", _compact(cost_totals.get("run_count")), ""),
            "",
            "## Command Evidence",
            "",
            "| Command | Status | Summary |",
            "| --- | --- | --- |",
        ]
    )
    for item in payload["command_evidence"]:
        lines.append(_row(str(item["command"]), str(item["status"]), str(item["summary"])))

    lines.extend(
        [
            "",
            "## Known Blockers",
            "",
            *[f"- {blocker}" for blocker in known_blockers],
            "",
            "## Release-readiness conclusion",
            "",
            _conclusion(smoke, failed_gates, known_blockers),
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _row(*cells: str) -> str:
    return "| " + " | ".join(_escape_cell(str(cell)) for cell in cells) + " |"


def _escape_cell(value: str) -> str:
    return value.replace("\n", " ").replace("|", "\\|")


def _compact(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, sort_keys=True, ensure_ascii=False)[:240]
    return str(value)


def _sidecar_details(item: Mapping[str, Any]) -> str:
    reasons = item.get("degraded_reasons") or item.get("reasons") or []
    if isinstance(reasons, str):
        reasons = [reasons]
    details = [str(reason) for reason in reasons if str(reason)]
    degraded_reason = item.get("degraded_reason")
    if degraded_reason:
        details.append(str(degraded_reason))
    runner_status = item.get("runner_status")
    if runner_status:
        details.append(f"runner={runner_status}")
    budget_status = item.get("budget_status")
    if budget_status:
        details.append(f"budget={budget_status}")
    return ", ".join(details) or "-"


def _impact_summary(foreground: Mapping[str, Any], latency: Mapping[str, Any]) -> str:
    return (
        f"foreground_blocking={foreground.get('foreground_sidecar_blocking')}; "
        f"foreground_ms={latency.get('foreground_ms', '-')}; "
        f"background_ms={latency.get('background_sidecar_ms', '-')}"
    )


def _doctor_summary(doctor: Mapping[str, Any]) -> str:
    diagnostics = doctor.get("diagnostics") or doctor.get("roles") or []
    degraded = [
        str(item.get("role"))
        for item in diagnostics
        if isinstance(item, Mapping) and item.get("status") != "ready"
    ]
    return "all roles ready" if not degraded else f"degraded roles: {', '.join(degraded)}"


def _cost_summary(
    totals: Mapping[str, Any],
    attribution: Mapping[str, Any],
    context: Mapping[str, Any],
) -> str:
    return (
        f"cost={_first_present(totals, attribution, 'total_estimated_cost_usd', 'estimated_cost_usd')}; "
        f"tokens={_total_tokens(totals, attribution)}; "
        f"context={context.get('context_admitted_tokens', '-')}"
    )


def _total_tokens(totals: Mapping[str, Any], attribution: Mapping[str, Any]) -> Any:
    total = totals.get("total_tokens")
    if total is not None:
        return total
    prompt = _first_present(totals, attribution, "total_prompt_tokens", "prompt_tokens", "input_tokens")
    completion = _first_present(totals, attribution, "total_completion_tokens", "completion_tokens", "output_tokens")
    if isinstance(prompt, (int, float)) and isinstance(completion, (int, float)):
        return prompt + completion
    return "-"


def _first_present(primary: Mapping[str, Any], fallback: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in primary and primary[key] is not None:
            return primary[key]
    for key in keys:
        if key in fallback and fallback[key] is not None:
            return fallback[key]
    return "-"


def _conclusion(smoke: Mapping[str, Any], failed_gates: int, blockers: Iterable[str]) -> str:
    real_blockers = [item for item in blockers if item != "None for deterministic production-closure smoke."]
    if smoke.get("status") == "passed" and failed_gates == 0 and not real_blockers:
        return (
            "The branch is production-closure-ready for deterministic local/runtime-learning validation. "
            "Live provider rollout still remains opt-in and approval-gated."
        )
    return (
        "The branch is not fully production-closure-ready until the failed gates or known blockers above are resolved. "
        "Enforcement must remain disabled."
    )
