"""Regressions for the context-engine host contract (ported subset).

Pins the host-side session-transition guarantees that external context engine
plugins (e.g. hermes-lcm) rely on. Ported from upstream
``9b5dae17a feat(context-engine): host contract`` — the
``_transition_context_engine_session`` lifecycle + ``reset_session_state``
delegation. (The plugin-discovery / slash-command guarantees #4/#5 depend on
gateway-plugin wiring not yet present on this branch and are tracked
separately.)
"""

from __future__ import annotations

from run_agent import AIAgent


def _bare_agent() -> AIAgent:
    agent = object.__new__(AIAgent)
    agent.session_id = "test-session"
    agent.model = "fake-model"
    agent.platform = "telegram"
    agent._gateway_session_key = "agent:main:telegram:dm:42"
    return agent


class _RecordingEngine:
    def __init__(self):
        self.context_length = 200_000
        self.events: list[str] = []
        self.start_kwargs: dict = {}

    def on_session_end(self, *a, **kw):
        self.events.append("on_session_end")

    def on_session_reset(self):
        self.events.append("on_session_reset")

    def on_session_start(self, sid, **kw):
        self.events.append("on_session_start")
        self.start_kwargs = kw

    def carry_over_new_session_context(self, *a, **kw):
        self.events.append("carry_over")


def test_transition_runs_full_lifecycle_in_order():
    engine = _RecordingEngine()
    agent = _bare_agent()
    agent.context_compressor = engine

    agent._transition_context_engine_session(
        old_session_id="old-sid",
        new_session_id="new-sid",
        previous_messages=[{"role": "user", "content": "hi"}],
        carry_over_context=True,
    )

    assert engine.events == [
        "on_session_end",
        "on_session_reset",
        "on_session_start",
        "carry_over",
    ]


def test_transition_passes_conversation_id_from_gateway_session_key():
    engine = _RecordingEngine()
    agent = _bare_agent()
    agent.context_compressor = engine

    agent._transition_context_engine_session(
        old_session_id="old-sid",
        new_session_id="new-sid",
        previous_messages=[{"role": "user", "content": "hi"}],
    )

    assert engine.start_kwargs.get("conversation_id") == "agent:main:telegram:dm:42"
    assert engine.start_kwargs.get("old_session_id") == "old-sid"
    assert engine.start_kwargs.get("platform") == "telegram"


def test_transition_skips_optional_hooks_when_engine_lacks_them():
    class MinimalEngine:
        def __init__(self):
            self.context_length = 100_000
            self.reset_called = False
            self.start_called_with = None

        def on_session_reset(self):
            self.reset_called = True

        def on_session_start(self, sid, **kw):
            self.start_called_with = (sid, kw)

    engine = MinimalEngine()
    agent = _bare_agent()
    agent.context_compressor = engine

    agent._transition_context_engine_session(
        old_session_id="old",
        new_session_id="new",
        previous_messages=[{"role": "user", "content": "hi"}],
        carry_over_context=True,
    )

    assert engine.reset_called is True
    assert engine.start_called_with is not None


def test_transition_no_engine_is_noop():
    agent = _bare_agent()
    agent.context_compressor = None
    # Must not raise when no engine is configured.
    agent._transition_context_engine_session(old_session_id="x", new_session_id="y")


def test_reset_session_state_default_callers_keep_reset_only_behavior():
    """Bare reset_session_state() (the cli.py call sites) only resets the engine."""
    engine = _RecordingEngine()
    agent = _bare_agent()
    agent.context_compressor = engine

    agent.reset_session_state()

    # No old_session_id / previous_messages → only the reset hook fires.
    assert engine.events == ["on_session_reset"]
    assert agent.session_total_tokens == 0
    assert agent._user_turn_count == 0
