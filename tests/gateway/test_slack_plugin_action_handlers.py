"""Tests for plugin-registered Slack Block Kit action handlers.

Covers:
* ``PluginContext.register_slack_action_handler`` validation + queuing
* ``PluginManager.get_slack_action_handlers`` accessor
* ``SlackAdapter.connect`` wiring those handlers into the AsyncApp
* Defensive wrapping: a plugin handler that raises does NOT take down
  the gateway and Slack still gets an ack.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Ensure the repo root is importable when this test runs directly
# ---------------------------------------------------------------------------
_repo = str(Path(__file__).resolve().parents[2])
if _repo not in sys.path:
    sys.path.insert(0, _repo)


# ---------------------------------------------------------------------------
# Mock slack-bolt so SlackAdapter can be imported even without the package
# ---------------------------------------------------------------------------

def _ensure_slack_mock() -> None:
    if "slack_bolt" in sys.modules and hasattr(sys.modules["slack_bolt"], "__file__"):
        return
    slack_bolt = MagicMock()
    slack_bolt.async_app.AsyncApp = MagicMock
    slack_bolt.adapter.socket_mode.async_handler.AsyncSocketModeHandler = MagicMock

    slack_sdk = MagicMock()
    slack_sdk.web.async_client.AsyncWebClient = MagicMock

    for name, mod in [
        ("slack_bolt", slack_bolt),
        ("slack_bolt.async_app", slack_bolt.async_app),
        ("slack_bolt.adapter", slack_bolt.adapter),
        ("slack_bolt.adapter.socket_mode", slack_bolt.adapter.socket_mode),
        ("slack_bolt.adapter.socket_mode.async_handler",
         slack_bolt.adapter.socket_mode.async_handler),
        ("slack_sdk", slack_sdk),
        ("slack_sdk.web", slack_sdk.web),
        ("slack_sdk.web.async_client", slack_sdk.web.async_client),
    ]:
        sys.modules.setdefault(name, mod)
    sys.modules.setdefault("aiohttp", MagicMock())


_ensure_slack_mock()

import plugins.platforms.slack.adapter as _slack_mod  # noqa: E402
_slack_mod.SLACK_AVAILABLE = True

from gateway.config import PlatformConfig  # noqa: E402
from plugins.platforms.slack.adapter import SlackAdapter  # noqa: E402

from hermes_cli.plugins import (  # noqa: E402
    PluginContext,
    PluginManager,
    PluginManifest,
)


# ---------------------------------------------------------------------------
# PluginContext.register_slack_action_handler — input validation + queuing
# ---------------------------------------------------------------------------

def _make_ctx(name: str = "test_plugin") -> tuple[PluginManager, PluginContext]:
    """Build a fresh PluginManager + PluginContext bound to it."""
    mgr = PluginManager()
    manifest = PluginManifest(
        name=name,
        version="0.1.0",
        description="test",
    )
    ctx = PluginContext(manifest=manifest, manager=mgr)
    return mgr, ctx


def _discard_created_task(coro):
    """Close connect-time watchdog coroutines in synchronous wiring tests."""
    coro.close()
    return MagicMock()


class TestRegisterSlackActionHandlerAPI:
    """Behaviour of ctx.register_slack_action_handler()."""

    def test_string_action_id_is_queued(self):
        mgr, ctx = _make_ctx()

        async def cb(ack, body, action):  # pragma: no cover - never called here
            await ack()

        ctx.register_slack_action_handler("inbox_sweep_approve", cb)

        handlers = mgr.get_slack_action_handlers()
        assert len(handlers) == 1
        action_id, callback, plugin_name = handlers[0]
        assert action_id == "inbox_sweep_approve"
        assert callback is cb
        assert plugin_name == "test_plugin"

    def test_regex_action_id_is_accepted(self):
        """slack_bolt accepts re.Pattern matchers — so should the plugin API."""
        import re as _re
        mgr, ctx = _make_ctx()

        async def cb(ack, body, action):  # pragma: no cover
            await ack()

        pat = _re.compile(r"^inbox_sweep_.*$")
        ctx.register_slack_action_handler(pat, cb)
        handlers = mgr.get_slack_action_handlers()
        assert handlers[0][0] is pat

    def test_constraint_dict_action_id_is_accepted(self):
        """slack_bolt also accepts {"action_id": ..., "block_id": ...} dicts."""
        mgr, ctx = _make_ctx()

        async def cb(ack, body, action):  # pragma: no cover
            await ack()

        constraint = {"action_id": "approve", "block_id": "row_3"}
        ctx.register_slack_action_handler(constraint, cb)
        handlers = mgr.get_slack_action_handlers()
        assert handlers[0][0] == constraint

    def test_non_callable_callback_raises(self):
        _mgr, ctx = _make_ctx()
        with pytest.raises(ValueError, match="non-callable"):
            ctx.register_slack_action_handler("approve", "not a function")  # type: ignore[arg-type]

    def test_empty_string_action_id_raises(self):
        _mgr, ctx = _make_ctx()

        async def cb(ack, body, action):  # pragma: no cover
            await ack()

        with pytest.raises(ValueError, match="empty action_id"):
            ctx.register_slack_action_handler("   ", cb)

    def test_none_action_id_raises(self):
        _mgr, ctx = _make_ctx()

        async def cb(ack, body, action):  # pragma: no cover
            await ack()

        with pytest.raises(ValueError, match="empty action_id"):
            ctx.register_slack_action_handler(None, cb)

    def test_get_slack_action_handlers_returns_copy(self):
        """The accessor should return a copy so callers can't mutate state."""
        mgr, ctx = _make_ctx()

        async def cb(ack, body, action):  # pragma: no cover
            await ack()

        ctx.register_slack_action_handler("a", cb)

        handlers = mgr.get_slack_action_handlers()
        handlers.clear()
        assert len(mgr.get_slack_action_handlers()) == 1

    def test_multiple_plugins_each_recorded(self):
        mgr = PluginManager()
        ctx_a = PluginContext(
            manifest=PluginManifest(name="plug_a", version="0", description=""),
            manager=mgr,
        )
        ctx_b = PluginContext(
            manifest=PluginManifest(name="plug_b", version="0", description=""),
            manager=mgr,
        )

        async def cb_a(ack, body, action):  # pragma: no cover
            await ack()

        async def cb_b(ack, body, action):  # pragma: no cover
            await ack()

        ctx_a.register_slack_action_handler("approve", cb_a)
        ctx_b.register_slack_action_handler("decline", cb_b)

        handlers = mgr.get_slack_action_handlers()
        assert {h[2] for h in handlers} == {"plug_a", "plug_b"}


class TestRegisterSlackViewHandlerAPI:
    """Plugins can register typed Slack modal submission handlers."""

    def test_typed_view_submission_is_queued(self):
        mgr, ctx = _make_ctx()

        async def cb(ack, body, view):  # pragma: no cover - not invoked here
            await ack()

        matcher = {"type": "view_submission", "callback_id": "triage_edit_submit"}
        ctx.register_slack_view_handler(matcher, cb)

        handlers = mgr.get_slack_view_handlers()
        assert handlers == [(matcher, cb, "test_plugin")]

    @pytest.mark.parametrize(
        "matcher",
        [
            "triage_edit_submit",
            {"type": "view_submission"},
            {"type": "message_action", "callback_id": "triage_edit_submit"},
            {"type": "view_submission", "callback_id": ""},
        ],
    )
    def test_malformed_matcher_is_rejected(self, matcher):
        _mgr, ctx = _make_ctx()

        async def cb(ack, body, view):  # pragma: no cover - not invoked here
            await ack()

        with pytest.raises(ValueError, match="view handler matcher"):
            ctx.register_slack_view_handler(matcher, cb)

    def test_synchronous_callback_is_rejected(self):
        _mgr, ctx = _make_ctx()

        def sync_cb(ack, body, view):
            return None

        with pytest.raises(ValueError, match="must be async"):
            ctx.register_slack_view_handler(
                {"type": "view_submission", "callback_id": "triage_edit_submit"},
                sync_cb,
            )

    def test_getter_returns_a_copy(self):
        mgr, ctx = _make_ctx()

        async def cb(ack, body, view):  # pragma: no cover - not invoked here
            await ack()

        ctx.register_slack_view_handler(
            {"type": "view_submission", "callback_id": "triage_edit_submit"},
            cb,
        )
        snapshot = mgr.get_slack_view_handlers()
        snapshot.clear()

        assert len(mgr.get_slack_view_handlers()) == 1


class TestRegisterSlackMessageObserverRegistration:

    def test_async_observer_is_queued(self):
        mgr, ctx = _make_ctx()

        async def observer(body):  # pragma: no cover - never called here
            return None

        ctx.register_slack_message_observer(observer)

        observers = mgr.get_slack_message_observers()
        assert len(observers) == 1
        callback, plugin_name = observers[0]
        assert callback is observer
        assert plugin_name == "test_plugin"

    def test_non_callable_observer_raises(self):
        _mgr, ctx = _make_ctx()
        with pytest.raises(ValueError, match="non-callable"):
            ctx.register_slack_message_observer("not a function")  # type: ignore[arg-type]

    def test_synchronous_observer_is_rejected(self):
        _mgr, ctx = _make_ctx()

        def observer(body):
            return None

        with pytest.raises(ValueError, match="async"):
            ctx.register_slack_message_observer(observer)

    def test_get_observers_returns_copy(self):
        mgr, ctx = _make_ctx()

        async def observer(body):  # pragma: no cover
            return None

        ctx.register_slack_message_observer(observer)
        observers = mgr.get_slack_message_observers()
        observers.clear()
        assert len(mgr.get_slack_message_observers()) == 1


# ---------------------------------------------------------------------------
# SlackAdapter.connect wires plugin-registered handlers into AsyncApp
# ---------------------------------------------------------------------------


def _connect_with_recording_app(
    adapter: SlackAdapter,
    *,
    plugin_handlers: list,
    plugin_view_handlers: list | None = None,
    plugin_message_observers: list | None = None,
) -> tuple[bool, list]:
    """Run adapter.connect() with mocks and return (result, registered_actions).

    Captures every action_id passed to ``app.action()`` so tests can
    assert that built-in handlers AND plugin-supplied handlers were
    wired up.
    """
    registered_actions: list = []  # list of (action_id, callback)
    registered_views: list = []  # list of (matcher, callback)
    registered_events: dict[str, object] = {}

    def mock_action(action_id):
        def decorator(fn):
            registered_actions.append((action_id, fn))
            return fn
        return decorator

    def mock_view(matcher):
        def decorator(fn):
            registered_views.append((matcher, fn))
            return fn
        return decorator

    def mock_event(event_type):
        def decorator(fn):
            registered_events[event_type] = fn
            return fn
        return decorator

    def mock_command(_cmd):
        def decorator(fn):
            return fn
        return decorator

    mock_app = MagicMock()
    mock_app.event = mock_event
    mock_app.command = mock_command
    mock_app.action = mock_action
    mock_app.view = mock_view
    mock_app.client = AsyncMock()

    mock_web_client = AsyncMock()
    mock_web_client.auth_test = AsyncMock(return_value={
        "user_id": "U_BOT",
        "user": "testbot",
        "team_id": "T_FAKE",
        "team": "FakeTeam",
    })

    fake_mgr = MagicMock()
    fake_mgr.get_slack_action_handlers.return_value = plugin_handlers
    fake_mgr.get_slack_view_handlers.return_value = plugin_view_handlers or []
    fake_mgr.get_slack_message_observers.return_value = plugin_message_observers or []
    adapter._test_plugin_manager = fake_mgr
    adapter._test_registered_events = registered_events
    adapter._test_registered_views = registered_views

    with patch.object(_slack_mod, "AsyncApp", return_value=mock_app), \
         patch.object(_slack_mod, "AsyncWebClient", return_value=mock_web_client), \
         patch.object(_slack_mod, "AsyncSocketModeHandler", return_value=MagicMock()), \
         patch.dict(os.environ, {"SLACK_APP_TOKEN": "xapp-fake"}), \
         patch("gateway.status.acquire_scoped_lock", return_value=(True, None)), \
         patch("gateway.status.release_scoped_lock"), \
         patch("hermes_cli.plugins.get_plugin_manager", return_value=fake_mgr), \
         patch("asyncio.create_task", side_effect=_discard_created_task):
        result = asyncio.run(adapter.connect())

    return result, registered_actions


class TestRegisterSlackMessageObserverAPI:
    """A plugin can receive a passive raw Slack message envelope."""

    def test_async_observer_is_queued_for_gateway_dispatch(self):
        manager, context = _make_ctx()

        async def observer(body):  # pragma: no cover - invoked by adapter tests
            assert body["event"]["channel"] == "C0BDD8M51UN"

        context.register_slack_message_observer(observer)

        observers = manager.get_slack_message_observers()
        assert observers == [(observer, "test_plugin")]


class TestSlackAdapterPluginMessageObserverWiring:
    """Raw observer intake is separate from normal agent authorization."""

    def test_unauthorized_mpim_peer_reaches_passive_observer(self):
        adapter = SlackAdapter(PlatformConfig(enabled=True, token="xoxb-fake"))
        received: list[dict] = []

        async def observer(body):
            received.append(body)

        manager = MagicMock()
        manager.get_slack_message_observers.return_value = [
            (observer, "slack-triage-actions")
        ]
        body = {
            "event": {
                "type": "message",
                "user": "U09J8G5JG5R",  # JJ: not authorized for Hermes chat
                "channel": "C0BDD8M51UN",
                "channel_type": "mpim",
                "ts": "1784815997.242419",
                "text": "Thank you! I'll review this today and get back to you by tomorrow.",
            }
        }

        with patch("hermes_cli.plugins.get_plugin_manager", return_value=manager):
            asyncio.run(adapter._dispatch_plugin_message_observers(body))

        assert received == [body]


class TestSlackAdapterPluginActionWiring:
    """connect() must register plugin-supplied action handlers on AsyncApp."""

    def test_plugin_handler_wired_into_app(self):
        config = PlatformConfig(enabled=True, token="xoxb-fake")
        adapter = SlackAdapter(config)

        async def my_handler(ack, body, action):  # pragma: no cover - not invoked
            await ack()

        plugin_handlers = [("inbox_sweep_approve", my_handler, "jarvis")]
        result, registered = _connect_with_recording_app(
            adapter, plugin_handlers=plugin_handlers,
        )

        assert result is True
        action_ids = [aid for aid, _cb in registered]
        # Built-in approval buttons remain registered…
        assert "hermes_approve_once" in action_ids
        assert "hermes_deny" in action_ids
        # …and the plugin's action_id was added.
        assert "inbox_sweep_approve" in action_ids

    def test_plugin_view_submission_handler_wired_into_app(self):
        config = PlatformConfig(enabled=True, token="xoxb-fake")
        adapter = SlackAdapter(config)

        async def submit_handler(ack, body, view):  # pragma: no cover - not invoked
            await ack()

        matcher = {"type": "view_submission", "callback_id": "triage_edit_submit"}
        result, _registered = _connect_with_recording_app(
            adapter,
            plugin_handlers=[],
            plugin_view_handlers=[(matcher, submit_handler, "slack-triage-actions")],
        )

        assert result is True
        assert matcher in [
            registered_matcher
            for registered_matcher, _callback in adapter._test_registered_views
        ]
        wrapped = next(
            callback
            for registered_matcher, callback in adapter._test_registered_views
            if registered_matcher == matcher
        )
        assert tuple(inspect.signature(wrapped).parameters) == ("ack", "body", "view")

    @pytest.mark.parametrize("error_type", [KeyboardInterrupt, SystemExit])
    def test_plugin_view_base_exception_does_not_escape_slack_dispatch(self, error_type):
        config = PlatformConfig(enabled=True, token="xoxb-fake")
        adapter = SlackAdapter(config)

        async def broken_handler(ack, body, view):
            raise error_type("plugin failure")

        matcher = {"type": "view_submission", "callback_id": "triage_edit_submit"}
        _result, _registered = _connect_with_recording_app(
            adapter,
            plugin_handlers=[],
            plugin_view_handlers=[(matcher, broken_handler, "buggy-plugin")],
        )
        wrapped = next(
            callback
            for registered_matcher, callback in adapter._test_registered_views
            if registered_matcher == matcher
        )
        ack = AsyncMock()

        asyncio.run(wrapped(ack, {"type": "view_submission"}, {"callback_id": "triage_edit_submit"}))

        ack.assert_awaited_once_with()

    def test_plugin_view_cancellation_propagates_for_gateway_lifecycle(self):
        config = PlatformConfig(enabled=True, token="xoxb-fake")
        adapter = SlackAdapter(config)

        async def cancelled_handler(ack, body, view):
            raise asyncio.CancelledError()

        matcher = {"type": "view_submission", "callback_id": "triage_edit_submit"}
        _result, _registered = _connect_with_recording_app(
            adapter,
            plugin_handlers=[],
            plugin_view_handlers=[(matcher, cancelled_handler, "cancelled-plugin")],
        )
        wrapped = next(
            callback
            for registered_matcher, callback in adapter._test_registered_views
            if registered_matcher == matcher
        )

        with pytest.raises(asyncio.CancelledError):
            asyncio.run(wrapped(AsyncMock(), {"type": "view_submission"}, {}))

    def test_no_plugin_handlers_does_not_break_connect(self):
        """An empty plugin handler list is the common case — must be a no-op."""
        config = PlatformConfig(enabled=True, token="xoxb-fake")
        adapter = SlackAdapter(config)

        result, registered = _connect_with_recording_app(
            adapter, plugin_handlers=[],
        )
        assert result is True
        # Built-ins still wired
        action_ids = [aid for aid, _cb in registered]
        assert "hermes_approve_once" in action_ids

    def test_connect_does_not_cache_message_observers(self):
        """Plugin reloads must apply without waiting for another reconnect."""
        config = PlatformConfig(enabled=True, token="xoxb-fake")
        adapter = SlackAdapter(config)

        async def observer(body):  # pragma: no cover - not invoked here
            return None

        result, _registered = _connect_with_recording_app(
            adapter,
            plugin_handlers=[],
            plugin_message_observers=[(observer, "triage")],
        )

        assert result is True
        assert not hasattr(adapter, "_plugin_message_observers")

    def test_message_event_resolves_observers_for_each_event(self):
        config = PlatformConfig(enabled=True, token="xoxb-fake")
        adapter = SlackAdapter(config)
        received: list[str] = []

        async def first_observer(body):
            received.append("first")

        async def second_observer(body):
            received.append("second")

        async def agent_handler(event, body):
            return None

        adapter._handle_slack_message = agent_handler
        result, _registered = _connect_with_recording_app(
            adapter,
            plugin_handlers=[],
            plugin_message_observers=[],
        )
        assert result is True
        manager = MagicMock()
        manager.get_slack_message_observers.side_effect = [
            [(first_observer, "first-plugin")],
            [(second_observer, "second-plugin")],
        ]
        body = {"event": {"type": "message", "user": "U09J8G5JG5R", "channel": "C0BDD8M51UN"}}

        with patch("hermes_cli.plugins.get_plugin_manager", return_value=manager):
            asyncio.run(adapter._test_registered_events["message"](body["event"], None, body))
            asyncio.run(adapter._test_registered_events["message"](body["event"], None, body))

        assert received == ["first", "second"]

    def test_message_event_observes_before_agent_authorization(self):
        """JJ's MPIM event must reach intake before normal agent rejection."""
        config = PlatformConfig(enabled=True, token="xoxb-fake")
        adapter = SlackAdapter(config)
        order: list[str] = []

        async def observer(body):
            order.append("observer")

        async def agent_handler(event, body):
            order.append("agent")

        adapter._handle_slack_message = agent_handler
        result, _registered = _connect_with_recording_app(
            adapter,
            plugin_handlers=[],
            plugin_message_observers=[(observer, "slack-triage-actions")],
        )
        assert result is True
        message_handler = adapter._test_registered_events["message"]
        body = {
            "event": {
                "type": "message",
                "user": "U09J8G5JG5R",
                "channel": "C0BDD8M51UN",
                "channel_type": "mpim",
                "ts": "1784815997.242419",
            }
        }

        with patch(
            "hermes_cli.plugins.get_plugin_manager",
            return_value=adapter._test_plugin_manager,
        ):
            asyncio.run(message_handler(body["event"], None, body))

        assert order == ["observer", "agent"]

    def test_observer_timeout_does_not_block_agent_dispatch(self, monkeypatch):
        config = PlatformConfig(enabled=True, token="xoxb-fake")
        adapter = SlackAdapter(config)
        observed: list[str] = []

        async def slow_observer(body):
            observed.append("started")
            await asyncio.Event().wait()

        async def agent_handler(event, body):
            observed.append("agent")

        adapter._handle_slack_message = agent_handler
        result, _registered = _connect_with_recording_app(
            adapter,
            plugin_handlers=[],
            plugin_message_observers=[(slow_observer, "slack-triage-actions")],
        )
        assert result is True
        monkeypatch.setattr(_slack_mod, "_PLUGIN_MESSAGE_OBSERVER_TIMEOUT_SECONDS", 0.01)
        message_handler = adapter._test_registered_events["message"]
        body = {"event": {"type": "message", "user": "U09J8G5JG5R", "channel": "C0BDD8M51UN"}}

        with patch(
            "hermes_cli.plugins.get_plugin_manager",
            return_value=adapter._test_plugin_manager,
        ):
            asyncio.run(message_handler(body["event"], None, body))

        assert observed == ["started", "agent"]

    def test_observer_cannot_mutate_normal_agent_authorization_event(self):
        config = PlatformConfig(enabled=True, token="xoxb-fake")
        adapter = SlackAdapter(config)
        agent_saw: list[str] = []

        async def mutating_observer(body):
            body["event"]["user"] = "U-CHANGED-BY-OBSERVER"

        async def agent_handler(event, body):
            agent_saw.append(event["user"])

        adapter._handle_slack_message = agent_handler
        result, _registered = _connect_with_recording_app(
            adapter,
            plugin_handlers=[],
            plugin_message_observers=[(mutating_observer, "slack-triage-actions")],
        )
        assert result is True
        body = {
            "event": {
                "type": "message",
                "user": "U-UNAUTHORIZED-PEER",
                "channel": "C0BDD8M51UN",
                "channel_type": "mpim",
            }
        }

        with patch(
            "hermes_cli.plugins.get_plugin_manager",
            return_value=adapter._test_plugin_manager,
        ):
            asyncio.run(adapter._test_registered_events["message"](body["event"], None, body))

        assert agent_saw == ["U-UNAUTHORIZED-PEER"]

    @pytest.mark.parametrize("error_type", [KeyboardInterrupt, SystemExit])
    def test_observer_base_exception_does_not_block_agent_dispatch(self, error_type):
        config = PlatformConfig(enabled=True, token="xoxb-fake")
        adapter = SlackAdapter(config)
        seen: list[str] = []

        async def interrupting_observer(body):
            raise error_type("observer failure")

        async def agent_handler(event, body):
            seen.append("agent")

        adapter._handle_slack_message = agent_handler
        result, _registered = _connect_with_recording_app(
            adapter,
            plugin_handlers=[],
            plugin_message_observers=[(interrupting_observer, "slack-triage-actions")],
        )
        assert result is True
        body = {"event": {"type": "message", "user": "U09J8G5JG5R", "channel": "C0BDD8M51UN"}}

        with patch(
            "hermes_cli.plugins.get_plugin_manager",
            return_value=adapter._test_plugin_manager,
        ):
            asyncio.run(adapter._test_registered_events["message"](body["event"], None, body))

        assert seen == ["agent"]

    def test_gateway_cancellation_propagates_without_agent_dispatch(self):
        config = PlatformConfig(enabled=True, token="xoxb-fake")
        adapter = SlackAdapter(config)
        agent_handler = AsyncMock()
        observer_started = asyncio.Event()

        async def waiting_observer(body):
            observer_started.set()
            await asyncio.Event().wait()

        adapter._handle_slack_message = agent_handler
        result, _registered = _connect_with_recording_app(
            adapter,
            plugin_handlers=[],
            plugin_message_observers=[(waiting_observer, "triage")],
        )
        assert result is True
        body = {
            "event": {
                "type": "message",
                "user": "U-UNAUTHORIZED-PEER",
                "channel": "C0BDD8M51UN",
            }
        }

        async def cancel_inflight_message_handler() -> None:
            task = asyncio.create_task(
                adapter._test_registered_events["message"](body["event"], None, body)
            )
            await observer_started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        with patch(
            "hermes_cli.plugins.get_plugin_manager",
            return_value=adapter._test_plugin_manager,
        ):
            asyncio.run(cancel_inflight_message_handler())

        agent_handler.assert_not_awaited()

    def test_message_observer_receives_full_body(self):
        config = PlatformConfig(enabled=True, token="xoxb-fake")
        adapter = SlackAdapter(config)
        seen: list[dict] = []

        async def observer(body):
            seen.append(body)

        manager = MagicMock()
        manager.get_slack_message_observers.return_value = [(observer, "triage")]
        body = {"event_id": "Ev1", "event": {"type": "message", "channel": "D1"}}
        with patch("hermes_cli.plugins.get_plugin_manager", return_value=manager):
            asyncio.run(adapter._dispatch_plugin_message_observers(body))

        assert seen == [body]
        assert seen[0] is not body

    def test_message_observer_exception_does_not_propagate(self):
        config = PlatformConfig(enabled=True, token="xoxb-fake")
        adapter = SlackAdapter(config)

        async def boom(body):
            raise RuntimeError("plugin bug")

        manager = MagicMock()
        manager.get_slack_message_observers.return_value = [(boom, "buggy_plugin")]
        with patch("hermes_cli.plugins.get_plugin_manager", return_value=manager):
            asyncio.run(adapter._dispatch_plugin_message_observers({"event": {}}))

    def test_plugin_exception_does_not_propagate_to_slack(self):
        """A misbehaving plugin handler must NOT crash slack_bolt's dispatch.

        The wrapper installed by connect() catches exceptions, logs them,
        and best-effort-acks so Slack stops retrying the click.
        """
        config = PlatformConfig(enabled=True, token="xoxb-fake")
        adapter = SlackAdapter(config)

        async def boom(ack, body, action):
            raise RuntimeError("plugin bug")

        plugin_handlers = [("explode", boom, "buggy_plugin")]
        _result, registered = _connect_with_recording_app(
            adapter, plugin_handlers=plugin_handlers,
        )

        wrapped = next(cb for aid, cb in registered if aid == "explode")
        ack = AsyncMock()
        body = {"foo": "bar"}
        action = {"action_id": "explode", "value": "x"}

        # Wrapper must swallow the RuntimeError.
        asyncio.run(wrapped(ack, body, action))

        # Slack still got an ack — best-effort fallback after exception.
        ack.assert_awaited()

    def test_plugin_handler_invoked_with_slack_args(self):
        """Happy path: the plugin's callback receives (ack, body, action)."""
        config = PlatformConfig(enabled=True, token="xoxb-fake")
        adapter = SlackAdapter(config)

        seen: dict = {}

        async def cb(ack, body, action):
            seen["body"] = body
            seen["action"] = action
            await ack()

        plugin_handlers = [("approve_x", cb, "plug_x")]
        _result, registered = _connect_with_recording_app(
            adapter, plugin_handlers=plugin_handlers,
        )

        wrapped = next(c for aid, c in registered if aid == "approve_x")
        ack = AsyncMock()
        asyncio.run(wrapped(ack, {"b": 1}, {"action_id": "approve_x"}))

        ack.assert_awaited_once_with()
        assert seen["body"] == {"b": 1}
        assert seen["action"] == {"action_id": "approve_x"}

    def test_wrapper_signature_only_exposes_slack_bolt_args(self):
        """Regression: slack_bolt introspects listener signatures and passes
        ``None`` for any parameter name it doesn't recognise. If the wrapper
        leaks closure variables (e.g. ``_cb``, ``_plugin_name``) into its
        signature via default args, they get clobbered to None at dispatch
        time and the wrapped callback becomes ``NoneType``.

        The wrapper must only expose ``(ack, body, action)``.
        """
        import inspect

        config = PlatformConfig(enabled=True, token="xoxb-fake")
        adapter = SlackAdapter(config)

        async def cb(ack, body, action):  # pragma: no cover
            await ack()

        plugin_handlers = [("approve_x", cb, "plug_x")]
        _result, registered = _connect_with_recording_app(
            adapter, plugin_handlers=plugin_handlers,
        )

        wrapped = next(c for aid, c in registered if aid == "approve_x")
        params = list(inspect.signature(wrapped).parameters)
        assert params == ["ack", "body", "action"], (
            f"wrapper exposes extra params slack_bolt would clobber: {params}"
        )

    def test_plugin_loader_failure_does_not_break_connect(self):
        """If get_plugin_manager() blows up, connect() must still succeed.

        Defensive belt-and-suspenders: the gateway should not refuse to
        start because the plugin layer is unhealthy.
        """
        config = PlatformConfig(enabled=True, token="xoxb-fake")
        adapter = SlackAdapter(config)

        registered_actions: list = []

        def mock_action(action_id):
            def decorator(fn):
                registered_actions.append((action_id, fn))
                return fn
            return decorator

        def _noop(_):
            def decorator(fn): return fn
            return decorator

        mock_app = MagicMock()
        mock_app.event = _noop
        mock_app.command = _noop
        mock_app.action = mock_action
        mock_app.client = AsyncMock()

        mock_web_client = AsyncMock()
        mock_web_client.auth_test = AsyncMock(return_value={
            "user_id": "U_BOT",
            "user": "testbot",
            "team_id": "T_FAKE",
            "team": "FakeTeam",
        })

        with patch.object(_slack_mod, "AsyncApp", return_value=mock_app), \
             patch.object(_slack_mod, "AsyncWebClient", return_value=mock_web_client), \
             patch.object(_slack_mod, "AsyncSocketModeHandler", return_value=MagicMock()), \
             patch.dict(os.environ, {"SLACK_APP_TOKEN": "xapp-fake"}), \
             patch("gateway.status.acquire_scoped_lock", return_value=(True, None)), \
             patch("gateway.status.release_scoped_lock"), \
             patch("hermes_cli.plugins.get_plugin_manager",
                   side_effect=RuntimeError("plugins broken")), \
             patch("asyncio.create_task", side_effect=_discard_created_task):
            result = asyncio.run(adapter.connect())

        assert result is True
        # Built-ins still wired even when plugin loader failed.
        action_ids = [aid for aid, _cb in registered_actions]
        assert "hermes_approve_once" in action_ids
