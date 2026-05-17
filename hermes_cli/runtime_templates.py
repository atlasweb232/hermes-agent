"""Prompt template loading for supervisor runtime orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List, Optional


REQUIRED_TEMPLATE_NAMES: tuple[str, ...] = (
    "supervisor_intake",
    "supervisor_initialization_protocol",
    "memory_packet",
    "speckit_planner_packet",
    "worker_delegation_packet",
    "worker_result",
    "validation_report",
    "session_summary",
)


def default_template_dir() -> Path:
    return Path(__file__).resolve().parent / "runtime_templates"


def template_path(name: str, *, template_dir: Optional[Path] = None) -> Path:
    clean = name.strip()
    if not clean:
        raise ValueError("template name is required")
    if "/" in clean or "\\" in clean or clean.endswith(".md"):
        raise ValueError("template name must be a bare name without extension")
    return (template_dir or default_template_dir()) / f"{clean}.md"


def load_template(name: str, *, template_dir: Optional[Path] = None) -> str:
    path = template_path(name, template_dir=template_dir)
    return path.read_text(encoding="utf-8")


def load_required_templates(
    names: Iterable[str] = REQUIRED_TEMPLATE_NAMES,
    *,
    template_dir: Optional[Path] = None,
) -> Dict[str, str]:
    templates: Dict[str, str] = {}
    for name in names:
        templates[name] = load_template(name, template_dir=template_dir)
    return templates


def missing_required_templates(
    names: Iterable[str] = REQUIRED_TEMPLATE_NAMES,
    *,
    template_dir: Optional[Path] = None,
) -> List[str]:
    missing: List[str] = []
    for name in names:
        if not template_path(name, template_dir=template_dir).exists():
            missing.append(name)
    return missing

