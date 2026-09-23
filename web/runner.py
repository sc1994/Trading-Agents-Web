"""Serial, credential-scoped adapter for the existing TradingAgents graph."""

import hashlib
import hmac
import json
import os
import secrets
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from threading import RLock
from types import SimpleNamespace
from uuid import UUID

from tradingagents.agents.utils.rating import RATING_REVIEW, extract_rating
from tradingagents.dataflows.utils import safe_ticker_component
from tradingagents.graph.checkpointer import checkpoint_step, clear_checkpoint, thread_id
from tradingagents.graph.trading_graph import TradingAgentsGraph
from web.reports import public_text, report_sections
from web.settings import SettingsService

# LLM/data clients read process-global environment variables throughout a run.
# All runner instances must share this lock, including config resolution.
_RUN_LOCK = RLock()


class GraphRunner:
    def __init__(self, settings: SettingsService, data_dir: Path):
        self.settings = settings
        self.data_dir = Path(data_dir).resolve()

    def _config(self, params: dict) -> tuple[dict, dict]:
        resolved = self.settings.resolve_run_config(params)
        config = deepcopy(resolved["config"])
        config["data_cache_dir"] = str(self.data_dir / "cache")
        config["memory_log_path"] = str(self.data_dir / "memory" / "trading_memory.md")
        return config, resolved["api_key_env"]

    @staticmethod
    def _signature(config: dict, params: dict) -> str:
        # Reuse the upstream signature without constructing clients or a graph.
        shape = SimpleNamespace(config=config, selected_analysts=params["analysts"])
        return TradingAgentsGraph._run_signature(shape, params["asset_type"])

    def _has_checkpoint(self, config: dict, params: dict) -> bool:
        if not config.get("checkpoint_enabled"):
            return False
        ticker = safe_ticker_component(params["ticker"]).upper()
        db_path = Path(config["data_cache_dir"]) / "checkpoints" / f"{ticker}.db"
        if not db_path.is_file():
            return False
        return checkpoint_step(
            config["data_cache_dir"], params["ticker"], params["date"],
            self._signature(config, params),
        ) is not None

    def _credential_binding(
        self, task_id: str, config: dict, params: dict, credentials: dict, *, create: bool = False
    ) -> bool:
        """Bind a shared checkpoint thread to its task and original credentials.

        Only a keyed HMAC is persisted, outside public reports/settings. A lost
        key or tag invalidates resume rather than trusting unbound raw state.
        Calls are serialized by the process-wide run lock.
        """
        private = self.data_dir / "private" / "checkpoint-bindings"
        key_path = private / "hmac.key"
        tid = thread_id(params["ticker"], params["date"], self._signature(config, params))
        tag_path = private / f"{tid}.tag"
        try:
            if create:
                private.mkdir(mode=0o700, parents=True, exist_ok=True)
                private.chmod(0o700)
                if not key_path.exists():
                    with os.fdopen(os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as file:
                        file.write(secrets.token_bytes(32))
            key = key_path.read_bytes()
            if len(key) != 32:
                return False
            # Include ownership because multiple Web tasks share graph threads.
            payload = json.dumps(
                [task_id, tid, credentials], sort_keys=True, separators=(",", ":")
            ).encode()
            tag = hmac.new(key, payload, hashlib.sha256).hexdigest().encode()
            if create:
                temporary = tag_path.with_suffix(".tmp")
                with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "wb") as file:
                    file.write(tag)
                temporary.replace(tag_path)
                return True
            return hmac.compare_digest(tag_path.read_bytes(), tag)
        except OSError:
            if create:
                raise
            return False

    def can_resume(self, task: dict) -> bool:
        """Check compatibility and current credentials without creating an LLM."""
        with _RUN_LOCK:
            try:
                params = task.get("params", task)
                config, credentials = self._config(params)
                task_id = str(UUID(task["id"]))
                return self._has_checkpoint(config, params) and self._credential_binding(
                    task_id, config, params, credentials
                )
            except (ValueError, KeyError, OSError, TypeError, AttributeError):
                return False

    def run(
        self, task: dict, emit: Callable[[str, dict], None], *, resume: bool = False
    ) -> tuple[dict, str]:
        """Stream public sections, preserving the graph's persistence lifecycle.

        The returned state is internal graph data, including the original final
        decision. Callers must never serialize the entire state to clients.
        """
        try:
            task_id = str(UUID(task["id"]))
        except (KeyError, TypeError, ValueError, AttributeError):
            raise ValueError("task id must be a UUID") from None
        params = task.get("params", task)
        with _RUN_LOCK:
            config, credentials = self._config(params)
            if resume and not (
                self._has_checkpoint(config, params)
                and self._credential_binding(task_id, config, params, credentials)
            ):
                raise ValueError("No compatible checkpoint is available")
            output = self.data_dir / "reports" / task_id
            if not output.resolve().is_relative_to(self.data_dir / "reports"):
                raise ValueError("task report directory is invalid")
            config["results_dir"] = str(output)
            previous_env = {key: os.environ.get(key) for key in credentials}

            def redact(text):
                for secret in sorted(set(credentials.values()), key=len, reverse=True):
                    if secret:
                        text = text.replace(secret, "[REDACTED]")
                return public_text(text)

            def sanitized(value):
                if isinstance(value, str):
                    return redact(value)
                if isinstance(value, dict):
                    return {key: sanitized(item) for key, item in value.items()}
                if isinstance(value, list):
                    return [sanitized(item) for item in value]
                return value

            graph = None
            try:
                os.environ.update(credentials)
                # Thread identities are shared across matching tasks: a rerun
                # must never accidentally resume an unrelated interrupted task.
                if not resume and self._has_checkpoint(config, params):
                    clear_checkpoint(
                        config["data_cache_dir"], params["ticker"], params["date"],
                        self._signature(config, params),
                    )
                if not resume and config.get("checkpoint_enabled") and not self._credential_binding(
                    task_id, config, params, credentials, create=True
                ):
                    raise RuntimeError("Unable to bind checkpoint credentials")
                graph = TradingAgentsGraph(
                    debug=False, config=config, selected_analysts=params["analysts"]
                )
                graph.ticker = params["ticker"]
                graph._resolve_pending_entries(params["ticker"])
                initial = graph.propagator.create_initial_state(
                    params["ticker"], params["date"], asset_type=params["asset_type"],
                    instrument_context=graph.resolve_instrument_context(
                        params["ticker"], params["asset_type"]
                    ),
                    past_context=graph.memory_log.get_past_context(
                        params["ticker"], as_of=graph._memory_as_of(params["date"])
                    ),
                )
                thread = graph.begin_checkpoint(
                    params["ticker"], params["date"], params["asset_type"]
                )
                args = graph.propagator.get_graph_args()
                if thread is not None:
                    args.setdefault("config", {}).setdefault("configurable", {})["thread_id"] = thread
                previous = {}
                final_state = None
                for state in graph.graph.stream(graph.checkpoint_input(initial), **args):
                    final_state = state
                    for section, content in report_sections(state).items():
                        text = redact(content)
                        if text.strip() and previous.get(section) != text:
                            previous[section] = text
                            emit("section", {"section": section, "text": text})
                if final_state is None or not final_state.get("final_trade_decision"):
                    raise RuntimeError("Graph produced no final decision")
                graph.curr_state = final_state
                rating = extract_rating(final_state["final_trade_decision"]) or RATING_REVIEW
                # Upstream logs/report writers take state, never the credential
                # envelope. Redact report text before writing their projections.
                safe_state = sanitized(final_state)
                graph._log_state(params["date"], safe_state)
                graph.memory_log.store_decision(
                    ticker=params["ticker"], trade_date=params["date"],
                    final_trade_decision=safe_state["final_trade_decision"],
                )
                graph.save_reports(safe_state, params["ticker"], save_path=output)
                graph.clear_checkpoint_on_success(
                    params["ticker"], params["date"], params["asset_type"]
                )
                return final_state, rating
            except Exception:
                # Provider/tool exceptions may contain keys, URLs or prompts.
                raise RuntimeError("Analysis failed; partial reports were preserved") from None
            finally:
                try:
                    if graph is not None:
                        graph.end_checkpoint()
                except Exception:
                    raise RuntimeError("Analysis cleanup failed; partial reports were preserved") from None
                finally:
                    for key, value in previous_env.items():
                        if value is None:
                            os.environ.pop(key, None)
                        else:
                            os.environ[key] = value
