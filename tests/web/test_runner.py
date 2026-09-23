import os
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from tradingagents.graph.checkpointer import get_checkpointer, thread_id
from tradingagents.graph.propagation import Propagator
from tradingagents.graph.trading_graph import TradingAgentsGraph
from web.runner import GraphRunner
from web.settings import SettingsService
from web.store import Store

TASK_ID = "846575f5-7d61-4772-85d0-d1d799154aba"
DECISION = "**Rating**: Overweight\n\n**Executive Summary**: Evidence-based plan"


@pytest.fixture
def setup_runner(tmp_path, monkeypatch):
    store = Store(tmp_path / "web.sqlite")
    settings = SettingsService(store)
    settings.update({"keys": {"openai": "secret-run-key", "fred": "secret-data-key"}})
    params = {
        "ticker": "AAPL", "date": "2024-01-02", "asset_type": "stock",
        "analysts": ["market"], "max_debate_rounds": 2, "max_risk_discuss_rounds": 3,
        "provider": "openai", "quick_model": "gpt-5.6-luna", "deep_model": "gpt-5.6",
        "checkpoint_enabled": True,
    }
    task = {"id": TASK_ID, "params": params, "ticker": "AAPL", "date": "2024-01-02"}
    initial = Propagator().create_initial_state("AAPL", "2024-01-02")
    market = {**initial, "market_report": "Market evidence"}
    debate = deepcopy(market)
    debate["investment_debate_state"]["bull_history"] = "Bull evidence"
    final = deepcopy(debate)
    final.update(investment_plan="Research plan", trader_investment_plan="Trader plan",
                 final_trade_decision=DECISION)
    final["risk_debate_state"]["judge_decision"] = DECISION
    control = SimpleNamespace(states=[initial, market, market, debate, final], graphs=[],
                              error=None, begin_error=False, resume=False, gate=None,
                              provider_key="secret-run-key", data_key="secret-data-key")

    class FakeGraph(TradingAgentsGraph):
        def __init__(self, *, debug, config, selected_analysts):
            assert debug is False
            assert os.environ["OPENAI_API_KEY"] == control.provider_key
            assert os.environ["FRED_API_KEY"] == control.data_key
            self.config, self.selected_analysts = config, selected_analysts
            self.propagator = Propagator()
            self.log_states_dict = {}
            self.memory_log = SimpleNamespace(
                get_past_context=Mock(return_value="Past known lesson"), store_decision=Mock()
            )
            self._resolve_pending_entries = Mock()
            self.resolve_instrument_context = Mock(return_value="Apple instrument context")
            self.end_checkpoint = Mock()
            self.clear_checkpoint_on_success = Mock()
            self._log_state = Mock(wraps=self._log_state)
            self.save_reports = Mock(wraps=self.save_reports)
            self.graph = SimpleNamespace(stream=self.stream)
            self.calls = []
            control.graphs.append(self)

        def begin_checkpoint(self, ticker, date, asset_type):
            self.calls.append(("begin", ticker, date, asset_type))
            self._resuming = control.resume
            if control.begin_error:
                raise RuntimeError("secret-run-key checkpoint failed")
            return "thread-123"

        def stream(self, graph_input, **args):
            self.input, self.args = graph_input, args
            if control.gate:
                control.gate()
            yield from control.states
            if control.error:
                raise control.error

    monkeypatch.setattr("web.runner.TradingAgentsGraph", FakeGraph)
    return GraphRunner(settings, tmp_path), task, control


def test_stream_emits_only_changes_and_preserves_graph_finalization(setup_runner, tmp_path):
    runner, task, control = setup_runner
    events = []
    state, rating = runner.run(task, lambda kind, payload: events.append((kind, payload)))
    assert state["final_trade_decision"] == DECISION
    assert rating == "Overweight"
    assert [payload for kind, payload in events if kind == "section"] == [
        {"section": "market_report", "text": "Market evidence"},
        {"section": "bull_history", "text": "Bull evidence"},
        {"section": "investment_plan", "text": "Research plan"},
        {"section": "trader_investment_plan", "text": "Trader plan"},
        {"section": "decision", "text": DECISION},
    ]
    graph = control.graphs[0]
    assert graph.input["past_context"] == "Past known lesson"
    assert graph.input["instrument_context"] == "Apple instrument context"
    assert graph.args == {"stream_mode": "values", "config": {
        "recursion_limit": 100, "configurable": {"thread_id": "thread-123"}}}
    graph.memory_log.get_past_context.assert_called_once_with("AAPL", as_of="2024-01-02")
    graph._resolve_pending_entries.assert_called_once_with("AAPL")
    graph._log_state.assert_called_once_with("2024-01-02", state)
    graph.memory_log.store_decision.assert_called_once_with(
        ticker="AAPL", trade_date="2024-01-02", final_trade_decision=DECISION)
    graph.clear_checkpoint_on_success.assert_called_once_with("AAPL", "2024-01-02", "stock")
    graph.save_reports.assert_called_once()
    graph.end_checkpoint.assert_called_once()
    assert graph.curr_state == state
    assert (tmp_path / "reports" / TASK_ID / "complete_report.md").is_file()
    assert len(list((tmp_path / "reports" / TASK_ID).rglob("*.json"))) == 1


@pytest.mark.parametrize("begin_error", [False, True])
def test_failure_restores_credentials_ends_checkpoint_and_retains_partial_reports(
    setup_runner, monkeypatch, begin_error
):
    runner, task, control = setup_runner
    monkeypatch.setenv("OPENAI_API_KEY", "original-key")
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    control.begin_error = begin_error
    control.states = control.states[:2]
    control.error = RuntimeError("secret-run-key failed")
    events = []
    with pytest.raises(RuntimeError) as exc:
        runner.run(task, lambda kind, payload: events.append((kind, payload)))
    assert "secret-run-key" not in str(exc.value)
    assert os.environ["OPENAI_API_KEY"] == "original-key"
    assert "FRED_API_KEY" not in os.environ
    graph = control.graphs[0]
    graph.end_checkpoint.assert_called_once()
    graph.clear_checkpoint_on_success.assert_not_called()
    graph.memory_log.store_decision.assert_not_called()
    if not begin_error:
        assert ("section", {"section": "market_report", "text": "Market evidence"}) in events


def test_public_payloads_redact_credentials_and_exclude_raw_model_messages(setup_runner, tmp_path):
    runner, task, control = setup_runner
    control.states[1]["market_report"] = "secret-run-key <think>private reasoning</think>Evidence"
    control.states[1]["messages"] = [{"content": "raw hidden tool payload"}]
    control.states[-1]["final_trade_decision"] = DECISION + " secret-run-key"
    control.states[-1]["risk_debate_state"]["judge_decision"] = DECISION + " secret-run-key"
    control.states[-1]["messages"] = [{"content": "raw hidden tool payload"}]
    events = []
    state, _ = runner.run(task, lambda kind, payload: events.append((kind, payload)))
    assert state["final_trade_decision"] == DECISION + " secret-run-key"
    assert "secret-run-key" not in repr(events)
    assert "private reasoning" not in repr(events)
    assert "raw hidden tool payload" not in repr(events)
    assert "Evidence" in repr(events)
    for report in (tmp_path / "reports" / TASK_ID).rglob("*"):
        if report.is_file():
            content = report.read_text()
            assert "secret-run-key" not in content
            assert "raw hidden tool payload" not in content
    assert "secret-run-key" not in str(control.graphs[0].memory_log.store_decision.call_args)


def _checkpoint(tmp_path):
    class State(TypedDict):
        value: int

    graph = StateGraph(State)
    graph.add_node("step", lambda state: {"value": state["value"] + 1})
    graph.add_edge(START, "step")
    graph.add_edge("step", END)
    signature = "analysts=market|debate=2|risk=3|asset=stock"
    with get_checkpointer(tmp_path / "cache", "AAPL") as saver:
        graph.compile(checkpointer=saver).invoke({"value": 1}, config={"configurable": {
            "thread_id": thread_id("AAPL", "2024-01-02", signature)}})


def _interrupted_checkpoint(setup_runner, tmp_path):
    runner, task, control = setup_runner
    control.error = RuntimeError("Interrupted stream")
    with pytest.raises(RuntimeError):
        runner.run(task, lambda *_: None)
    control.error = None
    control.graphs.clear()
    _checkpoint(tmp_path)


def test_resume_checks_signature_without_constructing_llm_and_fresh_run_clears_old_checkpoint(
    setup_runner, tmp_path
):
    runner, task, control = setup_runner
    assert runner.can_resume(task) is False
    assert not (tmp_path / "cache").exists()
    _interrupted_checkpoint(setup_runner, tmp_path)
    assert runner.can_resume(task) is True
    incompatible = deepcopy(task)
    incompatible["params"]["max_debate_rounds"] = 1
    assert runner.can_resume(incompatible) is False
    assert control.graphs == []
    runner.run(task, lambda *_: None)
    assert runner.can_resume(task) is False


def test_explicit_resume_uses_checkpoint_input_and_rejects_missing_checkpoint(setup_runner, tmp_path):
    runner, task, control = setup_runner
    with pytest.raises(ValueError, match="checkpoint"):
        runner.run(task, lambda *_: None, resume=True)
    assert control.graphs == []
    _interrupted_checkpoint(setup_runner, tmp_path)
    control.resume = True
    runner.run(task, lambda *_: None, resume=True)
    assert control.graphs[0].input is None


def test_unsafe_task_id_is_rejected_before_graph_construction(setup_runner):
    runner, task, control = setup_runner
    task["id"] = "../outside"
    with pytest.raises(ValueError, match="task"):
        runner.run(task, lambda *_: None)
    assert control.graphs == []


def test_process_lock_covers_entire_stream_and_restores_environment_on_success(setup_runner, monkeypatch):
    runner, task, control = setup_runner
    monkeypatch.setenv("OPENAI_API_KEY", "original-key")
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    started, release, second_entered = Event(), Event(), Event()

    def gate():
        if not started.is_set():
            started.set()
            assert release.wait(5)
        else:
            second_entered.set()

    control.gate = gate
    second_runner = GraphRunner(runner.settings, runner.data_dir)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(runner.run, task, lambda *_: None)
        assert started.wait(5)
        second = pool.submit(second_runner.run, task, lambda *_: None)
        try:
            assert not second_entered.wait(0.1)
        finally:
            release.set()
        first.result(timeout=5)
        second.result(timeout=5)
    assert second_entered.is_set()
    assert os.environ["OPENAI_API_KEY"] == "original-key"
    assert "FRED_API_KEY" not in os.environ


@pytest.mark.parametrize("source", ["provider", "data", "environment"])
def test_credential_rotation_rejects_old_secret_checkpoint_before_emitting(
    setup_runner, tmp_path, monkeypatch, source
):
    runner, task, control = setup_runner
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "old-environment-key")
    _interrupted_checkpoint(setup_runner, tmp_path)
    assert GraphRunner(runner.settings, tmp_path).can_resume(task) is True
    if source == "provider":
        runner.settings.update({"keys": {"openai": "rotated-provider-key"}})
        control.provider_key = "rotated-provider-key"
    elif source == "data":
        runner.settings.update({"keys": {"fred": "rotated-data-key"}})
        control.data_key = "rotated-data-key"
    else:
        monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "rotated-environment-key")
    control.resume = True
    control.states[0]["market_report"] = "secret-run-key secret-data-key old-environment-key"
    events = []
    assert runner.can_resume(task) is False
    with pytest.raises(ValueError, match="checkpoint"):
        runner.run(task, lambda kind, payload: events.append((kind, payload)), resume=True)
    assert events == []
    assert control.graphs == []
    assert not (tmp_path / "reports" / TASK_ID).exists()


def test_resume_fails_closed_for_unbound_checkpoint_or_different_task(setup_runner, tmp_path):
    runner, task, control = setup_runner
    _checkpoint(tmp_path)
    assert runner.can_resume(task) is False
    with pytest.raises(ValueError, match="checkpoint"):
        runner.run(task, lambda *_: None, resume=True)
    assert control.graphs == []
    _interrupted_checkpoint(setup_runner, tmp_path)
    other = {**task, "id": "dadb2df8-ff8a-4aa0-a73c-f979bb796088"}
    assert runner.can_resume(other) is False
    assert runner.can_resume(task) is True


@pytest.mark.parametrize("missing", ["hmac.key", "tag"])
def test_resume_binding_is_private_and_missing_binding_material_fails_closed(
    setup_runner, tmp_path, missing
):
    runner, task, _ = setup_runner
    _interrupted_checkpoint(setup_runner, tmp_path)
    private = tmp_path / "private" / "checkpoint-bindings"
    files = list(private.iterdir())
    assert len(files) == 2
    assert private.stat().st_mode & 0o777 == 0o700
    for path in files:
        assert path.stat().st_mode & 0o777 == 0o600
        assert b"secret-run-key" not in path.read_bytes()
        assert b"secret-data-key" not in path.read_bytes()
    target = private / "hmac.key" if missing == "hmac.key" else next(private.glob("*.tag"))
    target.unlink()
    restarted = GraphRunner(runner.settings, tmp_path)
    assert restarted.can_resume(task) is False
    with pytest.raises(ValueError, match="checkpoint"):
        restarted.run(task, lambda *_: None, resume=True)


def test_rating_is_parsed_before_redacting_credential_that_matches_rating(setup_runner):
    runner, task, control = setup_runner
    runner.settings.update({"keys": {"openai": "Overweight"}})
    control.provider_key = "Overweight"
    events = []
    state, rating = runner.run(task, lambda kind, payload: events.append((kind, payload)))
    assert rating == "Overweight"
    assert state["final_trade_decision"] == DECISION
    assert not any("Overweight" in payload["text"] for _, payload in events)


def test_checkpoint_teardown_error_cannot_leak_credentials(setup_runner, monkeypatch):
    runner, task, control = setup_runner
    monkeypatch.setenv("OPENAI_API_KEY", "original-key")

    def fail_teardown():
        control.graphs[0].end_checkpoint.side_effect = RuntimeError("secret-run-key teardown")

    control.gate = fail_teardown
    with pytest.raises(RuntimeError) as exc:
        runner.run(task, lambda *_: None)
    assert "secret-run-key" not in str(exc.value)
    assert os.environ["OPENAI_API_KEY"] == "original-key"
