import json
import sys
from unittest.mock import patch


def test_default_sidecar_tiers_and_roles_are_cost_ordered():
    from hermes_cli.config import load_config
    from hermes_cli.model_roles import get_model_role, list_model_tiers

    cfg = load_config()
    tiers = list_model_tiers(cfg)

    assert tiers["programmatic"]["provider"] == "none"
    assert tiers["programmatic"]["model"] == "none"
    assert tiers["programmatic"]["allow_llm"] is False
    assert tiers["cheap_reasoning"]["provider"] == "cerebras"
    assert tiers["cheap_reasoning"]["model"] == "gpt-oss-120b"
    assert tiers["cheap_reasoning"]["max_tokens"] == 2048
    assert tiers["strong_reasoning"]["provider"] == "deepseek"
    assert tiers["strong_reasoning"]["model"] == "deepseek-reasoner"
    assert tiers["code_critical"]["provider"] == "codex"
    assert "api_key" not in json.dumps(tiers).lower()
    assert "secret" not in json.dumps(tiers).lower()

    assert get_model_role(cfg, "progress_summarizer")["tier"] == "cheap_reasoning"
    assert get_model_role(cfg, "classifier")["tier"] == "programmatic"
    assert get_model_role(cfg, "extraction")["tier"] == "cheap_reasoning"
    assert get_model_role(cfg, "curator")["tier"] == "strong_reasoning"
    assert get_model_role(cfg, "curator")["config"]["provider"] == "deepseek"
    assert get_model_role(cfg, "learning_judge")["tier"] == "strong_reasoning"
    assert get_model_role(cfg, "learning_judge")["config"]["model"] == "deepseek-reasoner"
    assert get_model_role(cfg, "code_review_judge")["tier"] == "code_critical"


def test_top_level_sidecar_tiers_preferred_over_legacy_supervisor_config():
    from hermes_cli.model_roles import get_model_role, list_model_tiers

    cfg = {
        "sidecar_tiers": {
            "cheap_reasoning": {"provider": "deepseek", "model": "deepseek-chat"},
        },
        "sidecar_roles": {"extraction": "cheap_reasoning"},
        "supervisor": {
            "sidecar_model_tiers": {
                "cheap_reasoning": {"provider": "legacy", "model": "legacy-model"},
                "low_cost_reasoning": {"provider": "legacy-low", "model": "legacy-low-model"},
            },
            "sidecar_models": {"extraction": {"tier": "low_cost_reasoning"}},
        },
    }

    tiers = list_model_tiers(cfg)
    extraction = get_model_role(cfg, "extraction")

    assert tiers["cheap_reasoning"]["provider"] == "deepseek"
    assert tiers["cheap_reasoning"]["model"] == "deepseek-chat"
    assert extraction["tier"] == "cheap_reasoning"
    assert extraction["config"]["provider"] == "deepseek"


def test_routing_policy_uses_programmatic_exact_hits_and_limits_strong_models():
    from hermes_cli.config import load_config
    from hermes_cli.model_roles import plan_sidecar_route

    cfg = load_config()
    exact = plan_sidecar_route(
        cfg,
        "curator",
        retrieval_result="exact",
        confidence=0.95,
    )
    high_confidence = plan_sidecar_route(
        cfg,
        "learning_judge",
        retrieval_result="near",
        confidence=0.92,
    )
    low_confidence = plan_sidecar_route(
        cfg,
        "learning_judge",
        retrieval_result="near",
        confidence=0.41,
    )
    promotion = plan_sidecar_route(
        cfg,
        "learning_judge",
        retrieval_result="near",
        confidence=0.92,
        promotion_requested=True,
    )

    assert exact["call_llm"] is False
    assert exact["tier"] == "programmatic"
    assert exact["provider"] == "none"
    assert exact["reason"] == "exact_persisted_lesson_match"
    assert high_confidence["call_llm"] is False
    assert high_confidence["tier"] == "programmatic"
    assert low_confidence["call_llm"] is True
    assert low_confidence["tier"] == "strong_reasoning"
    assert promotion["requires_judge"] is True
    assert promotion["requires_operator"] is True
    assert promotion["tier"] == "strong_reasoning"


def test_operator_controls_are_dual_approval_and_advisory_only():
    from hermes_cli.model_roles import evaluate_operator_control

    pending = evaluate_operator_control(
        "promote_low_end_eval_finding",
        judge_approved=True,
        operator_approved=False,
    )
    approved = evaluate_operator_control(
        "promote_low_end_eval_finding",
        judge_approved=True,
        operator_approved=True,
    )
    realtime = evaluate_operator_control(
        "enable_realtime_provider",
        judge_approved=True,
        operator_approved=True,
    )
    export = evaluate_operator_control(
        "approve_export_bundle",
        judge_approved=True,
        operator_approved=True,
    )

    assert pending["allowed"] is False
    assert pending["missing"] == ["operator_approval"]
    assert approved["allowed"] is True
    assert approved["mode"] == "advisory"
    assert approved["enforcement_allowed"] is False
    assert realtime["allowed"] is True
    assert realtime["enforcement_allowed"] is False
    assert export["allowed"] is True
    assert export["requires"] == ["judge_approval", "operator_approval"]


def test_config_tiers_cli_json_exposes_sidecar_shape(_isolate_hermes_home, capsys):
    from hermes_cli import main as hermes_main

    with patch.object(sys, "argv", ["hermes", "config", "tiers", "--json"]):
        hermes_main.main()

    output = json.loads(capsys.readouterr().out)

    assert output["tiers"]["cheap_reasoning"]["provider"] == "cerebras"
    assert output["tiers"]["code_critical"]["provider"] == "codex"
    assert output["roles"]["classifier"] == "programmatic"
    assert output["roles"]["policy_review"] == "strong_reasoning"
