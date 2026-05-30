#!/usr/bin/env python3
"""Upstream drift watch for the Hermes fork.

Fetches the ``hermes-upstream`` remote (NousResearch/hermes-agent) and reports
how far the current branch has drifted, with a focus on *security-labeled*
upstream commits the fork has not yet absorbed. Run it on a schedule (cron /
systemd timer / CI) so the fork never silently falls 1000+ commits behind again.

Exit codes:
    0  drift within thresholds (or --report-only)
    2  security-labeled upstream commits exceed --max-security (actionable)
    3  git/remote error

Usage:
    python scripts/upstream_drift_watch.py [--remote hermes-upstream]
        [--branch main] [--max-behind N] [--max-security N] [--json]
        [--report-only]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from typing import Optional

# Commit-subject markers that indicate a security-relevant upstream change.
_SECURITY_RE = re.compile(
    r"(?i)\b(secur|redact|sanitiz|secret|credential|vault|tenant|isolat|"
    r"approval[- ]?bypass|auth|oauth|leak|cve|rls|injection|escap)\w*"
)


def _git(*args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def _fetch(remote: str, branch: str) -> None:
    _git("fetch", "--quiet", remote, branch)


def _ahead_behind(ref: str) -> tuple[int, int]:
    # left = upstream-only (behind), right = fork-only (ahead)
    out = _git("rev-list", "--left-right", "--count", f"{ref}...HEAD")
    behind, ahead = (int(x) for x in out.split())
    return ahead, behind


def _security_commits(ref: str, limit: int = 200) -> list[tuple[str, str]]:
    out = _git("log", f"{ref}", "--not", "HEAD", "--oneline", f"-n{limit}")
    hits: list[tuple[str, str]] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        sha, _, subject = line.partition(" ")
        if _SECURITY_RE.search(subject):
            hits.append((sha, subject))
    return hits


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--remote", default="hermes-upstream")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--max-behind", type=int, default=500)
    ap.add_argument("--max-security", type=int, default=0)
    ap.add_argument("--json", action="store_true")
    ap.add_argument(
        "--report-only",
        action="store_true",
        help="Always exit 0 regardless of thresholds (for dashboards).",
    )
    args = ap.parse_args(argv)

    ref = f"{args.remote}/{args.branch}"
    try:
        _fetch(args.remote, args.branch)
        ahead, behind = _ahead_behind(ref)
        merge_base = _git("merge-base", ref, "HEAD")
        mb_date = _git("show", "-s", "--format=%ci", merge_base)
        security = _security_commits(ref)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3

    report = {
        "ref": ref,
        "ahead": ahead,
        "behind": behind,
        "merge_base": merge_base[:12],
        "merge_base_date": mb_date,
        "security_commit_count": len(security),
        "security_commits": [{"sha": s, "subject": j} for s, j in security[:50]],
    }

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Upstream drift vs {ref}:")
        print(f"  behind: {behind}   ahead (fork-only): {ahead}")
        print(f"  merge-base: {merge_base[:12]} ({mb_date})")
        print(f"  security-labeled upstream commits not in HEAD: {len(security)}")
        for sha, subject in security[:25]:
            print(f"    {sha}  {subject}")
        if len(security) > 25:
            print(f"    ... and {len(security) - 25} more")

    if args.report_only:
        return 0
    if len(security) > args.max_security or behind > args.max_behind:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
