"""CLI subcommand: ``hermes dream <subcommand>``.

Dreaming is Hermes' bounded post-task consolidation loop. The runtime here is
intentionally lightweight: it persists a small state file, writes timestamped
review reports, and exposes pause/resume/status controls that can later be
backed by richer orchestration.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from hermes_constants import get_hermes_home


DEFAULT_INTERVAL_HOURS = 24
DEFAULT_MIN_IDLE_HOURS = 1.0
DEFAULT_PHASES = ("light", "rem", "deep")


def _dream_dir() -> Path:
    return get_hermes_home() / "logs" / "dreaming"


def _state_file() -> Path:
    return _dream_dir() / "state.json"


def _report_dir(run_id: str) -> Path:
    return _dream_dir() / run_id


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _fmt_ts(ts: Optional[str]) -> str:
    dt = _parse_iso(ts)
    if dt is None:
        return "never"
    delta = datetime.now(timezone.utc) - dt
    secs = int(delta.total_seconds())
    if secs < 60:
        return f"{secs}s ago"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


def _default_state() -> Dict[str, Any]:
    return {
        "last_run_at": None,
        "last_run_duration_seconds": None,
        "last_run_summary": None,
        "last_report_path": None,
        "last_phase": None,
        "last_review_reason": None,
        "last_run_summary_shown_at": None,
        "paused": False,
        "run_count": 0,
    }


def load_state() -> Dict[str, Any]:
    path = _state_file()
    if not path.exists():
        return _default_state()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            base = _default_state()
            base.update({k: v for k, v in data.items() if k in base or k.startswith("_")})
            return base
    except (OSError, json.JSONDecodeError):
        pass
    return _default_state()


def save_state(data: Dict[str, Any]) -> None:
    path = _state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".dream_state_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def set_paused(paused: bool) -> None:
    state = load_state()
    state["paused"] = bool(paused)
    save_state(state)


def is_paused() -> bool:
    return bool(load_state().get("paused"))


def _load_config() -> Dict[str, Any]:
    try:
        from hermes_cli.config import load_config
    except Exception:
        return {}
    cfg = load_config()
    dreaming = cfg.get("dreaming") if isinstance(cfg, dict) else {}
    return dreaming if isinstance(dreaming, dict) else {}


def is_enabled() -> bool:
    return bool(_load_config().get("enabled", True))


def get_interval_hours() -> int:
    cfg = _load_config()
    try:
        return int(cfg.get("interval_hours", DEFAULT_INTERVAL_HOURS))
    except (TypeError, ValueError):
        return DEFAULT_INTERVAL_HOURS


def get_min_idle_hours() -> float:
    cfg = _load_config()
    try:
        return float(cfg.get("min_idle_hours", DEFAULT_MIN_IDLE_HOURS))
    except (TypeError, ValueError):
        return DEFAULT_MIN_IDLE_HOURS


def get_phases() -> list[str]:
    cfg = _load_config()
    raw = cfg.get("phases", list(DEFAULT_PHASES))
    if not isinstance(raw, list):
        raw = list(DEFAULT_PHASES)
    phases = [str(p).strip() for p in raw if str(p).strip()]
    return phases or list(DEFAULT_PHASES)


@dataclass
class DreamRunResult:
    run_id: str
    status: str
    enabled: bool
    paused: bool
    reason: str
    started_at: str
    finished_at: str
    duration_seconds: float
    interval_hours: int
    min_idle_hours: float
    phases: list[str]
    report_path: Optional[str]
    summary: str
    dry_run: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _write_report(run_id: str, *, reason: str, dry_run: bool, started_at: str, finished_at: str,
                  duration_seconds: float, phases: list[str], summary: str) -> Path:
    report_root = _report_dir(run_id)
    report_root.mkdir(parents=True, exist_ok=True)
    report_path = report_root / "REPORT.md"
    body = [
        f"# Dreaming Report: {run_id}",
        "",
        f"- reason: {reason}",
        f"- dry run: {'yes' if dry_run else 'no'}",
        f"- started at: {started_at}",
        f"- finished at: {finished_at}",
        f"- duration seconds: {duration_seconds:.3f}",
        f"- phases: {', '.join(phases) if phases else '(none)'}",
        "",
        "## Summary",
        "",
        summary,
        "",
    ]
    report_path.write_text("\n".join(body), encoding="utf-8")
    return report_path


def run_dream_review(*, reason: str = "manual", dry_run: bool = False, force: bool = False) -> DreamRunResult:
    enabled = is_enabled()
    paused = is_paused()
    if not force and not enabled:
        return DreamRunResult(
            run_id="",
            status="disabled",
            enabled=enabled,
            paused=paused,
            reason=reason,
            started_at="",
            finished_at="",
            duration_seconds=0.0,
            interval_hours=get_interval_hours(),
            min_idle_hours=get_min_idle_hours(),
            phases=get_phases(),
            report_path=None,
            summary="dreaming is disabled in config",
            dry_run=dry_run,
        )
    if not force and paused:
        return DreamRunResult(
            run_id="",
            status="paused",
            enabled=enabled,
            paused=paused,
            reason=reason,
            started_at="",
            finished_at="",
            duration_seconds=0.0,
            interval_hours=get_interval_hours(),
            min_idle_hours=get_min_idle_hours(),
            phases=get_phases(),
            report_path=None,
            summary="dreaming is paused",
            dry_run=dry_run,
        )

    start = datetime.now(timezone.utc)
    run_id = f"dream_{start.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    phases = get_phases()
    interval_hours = get_interval_hours()
    min_idle_hours = get_min_idle_hours()
    summary = (
        "Dreaming pass completed with a bounded consolidation sweep.\n"
        f"Configured phases: {', '.join(phases)}.\n"
        "No production state was mutated by this review stub."
    )
    if dry_run:
        summary = (
            "Dry-run dreaming pass previewed the configured consolidation "
            f"phases: {', '.join(phases)}."
        )
    end = datetime.now(timezone.utc)
    duration_seconds = max(0.0, (end - start).total_seconds())
    report_path = None
    if not dry_run:
        report_path = str(
            _write_report(
                run_id,
                reason=reason,
                dry_run=dry_run,
                started_at=start.isoformat(),
                finished_at=end.isoformat(),
                duration_seconds=duration_seconds,
                phases=phases,
                summary=summary,
            )
        )

    state = load_state()
    state["last_run_at"] = end.isoformat()
    state["last_run_duration_seconds"] = duration_seconds
    state["last_run_summary"] = summary
    state["last_report_path"] = report_path
    state["last_phase"] = phases[-1] if phases else None
    state["last_review_reason"] = reason
    state["run_count"] = int(state.get("run_count", 0) or 0) + 1
    save_state(state)

    return DreamRunResult(
        run_id=run_id,
        status="completed",
        enabled=enabled,
        paused=paused,
        reason=reason,
        started_at=start.isoformat(),
        finished_at=end.isoformat(),
        duration_seconds=duration_seconds,
        interval_hours=interval_hours,
        min_idle_hours=min_idle_hours,
        phases=phases,
        report_path=report_path,
        summary=summary,
        dry_run=dry_run,
    )


def _cmd_status(args) -> int:
    state = load_state()
    enabled = is_enabled()
    paused = bool(state.get("paused", False))
    status_line = "ENABLED" if enabled and not paused else "PAUSED" if paused else "DISABLED"
    phases = ", ".join(get_phases())
    print(f"dreaming: {status_line}")
    print(f"  runs:           {state.get('run_count', 0)}")
    print(f"  last run:       {_fmt_ts(state.get('last_run_at'))}")
    print(f"  interval:       every {get_interval_hours()}h")
    print(f"  min idle:       {get_min_idle_hours()}h")
    print(f"  phases:         {phases}")
    if state.get("last_phase"):
        print(f"  last phase:     {state.get('last_phase')}")
    if state.get("last_review_reason"):
        print(f"  last reason:    {state.get('last_review_reason')}")
    if state.get("last_report_path"):
        report_path = Path(str(state["last_report_path"]))
        suffix = "" if report_path.exists() else " (missing)"
        print(f"  last report:    {report_path}{suffix}")
    if state.get("last_run_summary"):
        summary = str(state["last_run_summary"])
        if "\n" in summary:
            first, *rest = summary.splitlines()
            print(f"  last summary:   {first}")
            for line in rest:
                print(f"                  {line}")
        else:
            print(f"  last summary:   {summary}")
    return 0


def _cmd_run(args) -> int:
    result = run_dream_review(
        reason=getattr(args, "reason", "") or "manual",
        dry_run=bool(getattr(args, "dry_run", False)),
        force=bool(getattr(args, "force", False)),
    )
    if getattr(args, "json", False):
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        return 0 if result.status == "completed" else 1
    if result.status == "disabled":
        print("dreaming: disabled via config; enable with `dreaming.enabled: true`")
        return 1
    if result.status == "paused":
        print("dreaming: paused; resume with `hermes dream resume` or pass --force")
        return 1
    if result.dry_run:
        print("dreaming: dry-run preview completed")
    else:
        print("dreaming: review completed")
    print(f"  run:     {result.run_id}")
    print(f"  phases:  {', '.join(result.phases)}")
    print(f"  summary: {result.summary}")
    if result.report_path:
        print(f"  report:  {result.report_path}")
    return 0


def _cmd_pause(args) -> int:
    set_paused(True)
    print("dreaming: paused")
    return 0


def _cmd_resume(args) -> int:
    set_paused(False)
    print("dreaming: resumed")
    return 0


def _cmd_review(args) -> int:
    path_arg = getattr(args, "path", "") or ""
    state = load_state()
    report_path = Path(path_arg) if path_arg else None
    if report_path is None and state.get("last_report_path"):
        report_path = Path(str(state["last_report_path"]))
    if report_path is None:
        print("dreaming: no report available yet")
        return 1
    if not report_path.exists():
        print(f"dreaming: report not found: {report_path}")
        return 1
    print(report_path.read_text(encoding="utf-8"))
    return 0


def register_cli(parent: argparse.ArgumentParser) -> None:
    parent.set_defaults(func=lambda a: (parent.print_help(), 0)[1])
    subs = parent.add_subparsers(dest="dream_command")

    p_status = subs.add_parser("status", help="Show dream state and the latest review summary")
    p_status.set_defaults(func=_cmd_status)

    p_run = subs.add_parser("run", help="Run a dream consolidation pass now")
    p_run.add_argument("--reason", default="manual", help="Reason to record for the review")
    p_run.add_argument("--dry-run", action="store_true", help="Preview the review without writing a report")
    p_run.add_argument("--force", action="store_true", help="Run even when paused or disabled")
    p_run.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    p_run.set_defaults(func=_cmd_run)

    p_pause = subs.add_parser("pause", help="Pause dreaming until resumed")
    p_pause.set_defaults(func=_cmd_pause)

    p_resume = subs.add_parser("resume", help="Resume dreaming")
    p_resume.set_defaults(func=_cmd_resume)

    p_review = subs.add_parser("review", help="Print the latest dream report")
    p_review.add_argument("--path", default="", help="Explicit report path to print")
    p_review.set_defaults(func=_cmd_review)
