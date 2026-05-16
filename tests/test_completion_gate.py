import json
import subprocess

from hermes_cli.completion_gate import (
    append_gate_to_delegate_payload,
    enforce_final_response_gate,
    resolve_repo_path_from_texts,
    run_completion_gate,
)


def _git(repo, *args):
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )


def _init_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "init")
    return repo


def test_completion_gate_passes_clean_repo(tmp_path):
    repo = _init_repo(tmp_path)

    result = run_completion_gate(repo_path=repo, config={"supervisor": {"completion_gate": {"enabled": True}}})

    assert result.status == "passed"
    assert result.passed is True
    assert {check.name for check in result.checks} == {
        "git_unmerged_paths",
        "conflict_markers",
        "diff_check",
    }


def test_completion_gate_blocks_conflict_markers(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "broken.txt").write_text("<<<<<<< HEAD\nours\n=======\ntheirs\n>>>>>>>\n", encoding="utf-8")
    _git(repo, "add", "broken.txt")

    result = run_completion_gate(repo_path=repo, config={"supervisor": {"completion_gate": {"enabled": True}}})

    assert result.status == "blocked"
    failed = {check.name for check in result.checks if not check.passed}
    assert "conflict_markers" in failed


def test_delegate_payload_is_blocked_when_gate_fails(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "broken.txt").write_text("<<<<<<< HEAD\n", encoding="utf-8")
    _git(repo, "add", "broken.txt")
    gate = run_completion_gate(repo_path=repo, config={"supervisor": {"completion_gate": {"enabled": True}}})

    payload = append_gate_to_delegate_payload(
        json.dumps({"results": [{"task_index": 0, "status": "completed", "summary": "done"}]}),
        gate,
    )
    parsed = json.loads(payload)

    assert parsed["status"] == "blocked"
    assert parsed["results"][0]["status"] == "blocked"
    assert parsed["results"][0]["worker_status"] == "completed"


def test_final_response_guard_suppresses_success_claim(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "broken.txt").write_text("<<<<<<< HEAD\n", encoding="utf-8")
    _git(repo, "add", "broken.txt")
    gate = run_completion_gate(repo_path=repo, config={"supervisor": {"completion_gate": {"enabled": True}}})

    response = enforce_final_response_gate("Done, conflicts resolved and committed.", gate)

    assert response.startswith("Blocked: deterministic completion gate did not pass.")
    assert "suppressed" in response
    assert "conflict_markers" in response


def test_repo_path_detects_absolute_git_repo(tmp_path):
    repo = _init_repo(tmp_path)

    resolved = resolve_repo_path_from_texts([f"Repository: {repo}"])

    assert resolved == str(repo.resolve())
