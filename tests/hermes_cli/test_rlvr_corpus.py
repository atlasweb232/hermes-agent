"""Tests for the RLVR rollout-group corpus schema (teacher-independence, embedded).

Covers: model-independent reward, GRPO group-relative advantages, the learnable-signal
predicate, SFT/DPO derivations, the in-band oracle provenance, and round-trip persistence.
"""

from __future__ import annotations

from hermes_cli.rlvr_corpus import (
    RLVRRolloutGroup,
    build_rollout_group,
    compute_group_advantages,
    derive_preference_pairs,
    derive_sft_examples,
    ensure_rlvr_schema,
    get_rollout_group,
    list_rollout_groups,
    reward_from_verification,
    upsert_rollout_group,
)
from hermes_cli.verification_evidence import verification_record_from_gate


def _gate(passed: bool, *, n_pass: int = 1, n_fail: int = 0):
    checks = [
        {"name": "build", "passed": True, "skipped": False, "command": ["true"], "returncode": 0}
        for _ in range(n_pass)
    ] + [
        {"name": "build", "passed": False, "skipped": False, "command": ["false"], "returncode": 1}
        for _ in range(n_fail)
    ]
    return {
        "enabled": True,
        "status": "passed" if passed else "blocked",
        "repo_path": "/repo",
        "passed": passed,
        "checks": checks,
    }


def _record(passed: bool, *, held_out: bool = False, task_id: str = "t", **kw):
    return verification_record_from_gate(
        _gate(passed, **kw), task_id=task_id, tenant_id="A", repo_id="r", held_out=held_out
    )


def _group(attempts, **kw):
    return build_rollout_group(
        task={"task_id": "t1", "goal": "implement parser", "prompt_summary": "write a parser"},
        policy={"worker_model": "gemma-2b", "worker_version": "v1"},
        attempts=attempts,
        tenant_id="A",
        repo_id="r",
        dataset_family="policy_playbook",
        **kw,
    )


# ── reward is the oracle's verdict, not a model's ───────────────────────────

def test_reward_is_model_independent_binary():
    assert reward_from_verification(_record(True).to_evidence_block()) == 1.0
    assert reward_from_verification(_record(False).to_evidence_block()) == 0.0
    assert reward_from_verification(None) == 0.0
    assert reward_from_verification({"status": "passed"}) == 0.0  # passed flag absent → fail-closed


def test_oracle_block_asserts_teacher_independence():
    group = _group([("attempt a", _record(True))])
    oracle = group.to_dict()["oracle"]
    assert oracle["reward_source"] == "model_independent"
    assert oracle["judge_in_reward_loop"] is False
    assert oracle["kind"] == "completion_gate"


# ── GRPO group-relative advantages ──────────────────────────────────────────

def test_group_relative_advantages_sum_to_zero():
    group = _group([
        ("pass a", _record(True)),
        ("fail b", _record(False)),
        ("pass c", _record(True)),
        ("fail d", _record(False)),
    ])
    # baseline = mean reward = 0.5; advantages = +0.5 / -0.5
    advs = [r.advantage for r in group.rollouts]
    assert abs(sum(advs)) < 1e-9
    assert sorted(advs) == [-0.5, -0.5, 0.5, 0.5]
    assert group.mean_reward == 0.5


def test_compute_group_advantages_empty_is_noop():
    compute_group_advantages([])  # must not raise


# ── learnable-signal predicate ──────────────────────────────────────────────

def test_all_pass_group_has_no_grpo_signal_but_is_sft_usable():
    group = _group([("pass a", _record(True)), ("pass b", _record(True))])
    # identical reward → GRPO advantage is zero everywhere → no contrastive signal …
    assert group.has_learnable_signal is False
    # … but verified rollouts are still rejection-sampling/SFT material
    assert group.n_verified == 2
    assert "sft" in group.supported_methods()
    assert "dpo" not in group.supported_methods()


def test_mixed_group_is_learnable_and_supports_dpo():
    group = _group([("pass a", _record(True)), ("fail b", _record(False))])
    assert group.has_learnable_signal is True
    assert set(group.supported_methods()) >= {"sft", "dpo", "grpo", "rlvr"}


def test_all_fail_group_has_no_verified_signal():
    group = _group([("fail a", _record(False)), ("fail b", _record(False))])
    assert group.n_verified == 0
    assert group.has_learnable_signal is False
    assert group.supported_methods() == []


def test_held_out_counts_tracked():
    group = _group([
        ("pass visible", _record(True, held_out=False)),
        ("pass held-out", _record(True, held_out=True)),
        ("fail b", _record(False)),
    ])
    assert group.n_verified == 2
    assert group.n_held_out_verified == 1
    assert group.oracle_block()["held_out_available"] is True


# ── derivations into the existing mlops_corpus shapes ───────────────────────

def test_derive_sft_uses_only_verified_rollouts():
    group = _group([
        ("good code", _record(True)),
        ("broken code", _record(False)),
        ("also good", _record(True)),
    ])
    sft = derive_sft_examples(group)
    assert len(sft) == 2  # only the verified ones
    md = sft[0].to_dict()["metadata"]
    assert md["reward_source"] == "model_independent"
    assert md["reward"] == 1.0


def test_derive_preference_pairs_prefers_held_out_chosen():
    group = _group([
        ("visible pass", _record(True, held_out=False)),
        ("held-out pass", _record(True, held_out=True)),
        ("fail", _record(False)),
    ])
    pairs = derive_preference_pairs(group)
    assert len(pairs) == 1
    pd = pairs[0].to_dict()
    assert pd["chosen"] == "held-out pass"   # held-out beats visible as chosen
    assert pd["rejected"] == "fail"


def test_derive_preference_pairs_empty_without_both_classes():
    assert derive_preference_pairs(_group([("p", _record(True))])) == []
    assert derive_preference_pairs(_group([("f", _record(False))])) == []


# ── persistence round-trip ──────────────────────────────────────────────────

def test_rollout_group_persists_and_round_trips(tmp_path):
    from hermes_state import SessionDB

    db = SessionDB(tmp_path / "state.db")
    try:
        group = _group([
            ("pass a", _record(True, held_out=True)),
            ("fail b", _record(False)),
        ])
        upsert_rollout_group(db, group)

        fetched = get_rollout_group(db, group.group_id)
        assert fetched is not None
        assert fetched.n_verified == 1
        assert fetched.n_held_out_verified == 1
        assert fetched.rollouts[0].verification.get("evidence_sha256")
        # advantage survived the round-trip
        assert abs(sum(r.advantage for r in fetched.rollouts)) < 1e-9

        learnable = list_rollout_groups(db, tenant_id="A", learnable_only=True)
        assert any(g.group_id == group.group_id for g in learnable)
    finally:
        db.close()


def test_list_excludes_non_learnable_when_filtered(tmp_path):
    from hermes_state import SessionDB

    db = SessionDB(tmp_path / "state.db")
    try:
        all_pass = build_rollout_group(
            task={"task_id": "all-pass", "goal": "g", "prompt_summary": "p"},
            policy={"worker_model": "m"},
            attempts=[("a", _record(True, task_id="all-pass")), ("b", _record(True, task_id="all-pass"))],
            tenant_id="A", repo_id="r",
        )
        upsert_rollout_group(db, all_pass)
        learnable = list_rollout_groups(db, tenant_id="A", learnable_only=True)
        assert all(g.group_id != all_pass.group_id for g in learnable)
        everything = list_rollout_groups(db, tenant_id="A", learnable_only=False)
        assert any(g.group_id == all_pass.group_id for g in everything)
    finally:
        db.close()
