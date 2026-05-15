"""Tests for ``hermes dream`` CLI behavior."""

from __future__ import annotations

import importlib
from argparse import Namespace


def _dream_env(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    from hermes_cli import dream
    importlib.reload(dream)
    return dream


def test_status_reports_defaults(tmp_path, monkeypatch, capsys):
    dream = _dream_env(tmp_path, monkeypatch)

    assert dream._cmd_status(Namespace()) == 0
    out = capsys.readouterr().out
    assert "dreaming: ENABLED" in out
    assert "phases:         light, rem, deep" in out
    assert "min idle:       1.0h" in out


def test_run_creates_report_and_updates_state(tmp_path, monkeypatch, capsys):
    dream = _dream_env(tmp_path, monkeypatch)

    assert dream._cmd_run(Namespace(reason="task complete", dry_run=False, force=False, json=False)) == 0
    out = capsys.readouterr().out
    assert "dreaming: review completed" in out
    assert "report:" in out

    state = dream.load_state()
    assert state["run_count"] == 1
    assert state["last_run_at"] is not None
    assert state["last_report_path"]
    assert (tmp_path / "logs" / "dreaming").is_dir()
    assert (tmp_path / "logs" / "dreaming" / "state.json").exists()


def test_pause_and_resume_toggle_state(tmp_path, monkeypatch):
    dream = _dream_env(tmp_path, monkeypatch)

    assert dream._cmd_pause(Namespace()) == 0
    assert dream.is_paused() is True
    assert dream._cmd_resume(Namespace()) == 0
    assert dream.is_paused() is False


def test_review_prints_last_report(tmp_path, monkeypatch, capsys):
    dream = _dream_env(tmp_path, monkeypatch)

    dream._cmd_run(Namespace(reason="review test", dry_run=False, force=False, json=False))
    capsys.readouterr()

    assert dream._cmd_review(Namespace(path="")) == 0
    out = capsys.readouterr().out
    assert "# Dreaming Report:" in out
    assert "review test" in out
