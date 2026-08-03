"""Tests for extended Slack plugin observer and modal-view contracts."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock, patch
import os

import pytest

from gateway.config import PlatformConfig
from hermes_cli.plugins import PluginContext, PluginManager, PluginManifest
import plugins.platforms.slack.adapter as slack_mod
from plugins.platforms.slack.adapter import SlackAdapter


def _context(name: str = "triage") -> tuple[PluginManager, PluginContext]:
    manager = PluginManager()
    manifest = PluginManifest(name=name, version="1", description="test")
    return manager, PluginContext(manifest=manifest, manager=manager)


@pytest.mark.asyncio
async def test_registers_async_message_observer_and_returns_copy():
    manager, context = _context()

    async def observer(body):
        body["event"]["text"] = "mutated"

    context.register_slack_message_observer(observer)

    assert manager.get_slack_message_observers() == [(observer, "triage")]
    source = {"event": {"text": "original"}}
    adapter = SlackAdapter(PlatformConfig(enabled=True, token="xoxb-test"))
    with patch("hermes_cli.plugins.get_plugin_manager", return_value=manager):
        await adapter._dispatch_plugin_message_observers(source)
    assert source == {"event": {"text": "original"}}


def test_message_observer_requires_async_callback():
    _manager, context = _context()

    def sync_observer(_body):
        return None

    with pytest.raises(ValueError, match="must be async"):
        context.register_slack_message_observer(sync_observer)


@pytest.mark.asyncio
async def test_message_observer_failures_are_isolated():
    manager, context = _context()
    calls: list[str] = []

    async def broken(_body):
        calls.append("broken")
        raise SystemExit("plugin bug")

    async def healthy(_body):
        calls.append("healthy")

    context.register_slack_message_observer(broken)
    context.register_slack_message_observer(healthy)
    adapter = SlackAdapter(PlatformConfig(enabled=True, token="xoxb-test"))

    with patch("hermes_cli.plugins.get_plugin_manager", return_value=manager):
        await adapter._dispatch_plugin_message_observers({"event": {"text": "hello"}})

    assert calls == ["broken", "healthy"]


@pytest.mark.asyncio
async def test_message_observer_timeout_is_hard_even_if_callback_suppresses_cancel(
    monkeypatch,
):
    manager, context = _context()
    release = asyncio.Event()

    async def stubborn(_body):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            # A broken plugin can suppress cooperative cancellation. Its bug
            # must not turn the observer deadline into an unbounded wait.
            await release.wait()

    context.register_slack_message_observer(stubborn)
    adapter = SlackAdapter(PlatformConfig(enabled=True, token="xoxb-test"))
    monkeypatch.setattr(slack_mod, "_PLUGIN_MESSAGE_OBSERVER_TIMEOUT_SECONDS", 0.01)

    try:
        with patch("hermes_cli.plugins.get_plugin_manager", return_value=manager):
            await asyncio.wait_for(
                adapter._dispatch_plugin_message_observers({"event": {}}),
                timeout=0.2,
            )
    finally:
        release.set()
        await asyncio.sleep(0)


def test_registers_only_typed_modal_view_matchers():
    manager, context = _context()

    async def callback(ack, body, view):
        await ack()

    matcher = {"type": "view_submission", "callback_id": "triage_edit_submit"}
    context.register_slack_view_handler(matcher, callback)
    assert manager.get_slack_view_handlers() == [(matcher, callback, "triage")]

    with pytest.raises(ValueError, match="supported view type"):
        context.register_slack_view_handler(
            {"type": "block_actions", "callback_id": "too_broad"}, callback
        )
    with pytest.raises(ValueError, match="must be async"):
        context.register_slack_view_handler(matcher, lambda *_args: None)


def test_force_rediscovery_clears_extended_slack_handlers(monkeypatch):
    manager, context = _context()

    async def callback(*_args):
        return None

    context.register_slack_action_handler("action", callback)
    context.register_slack_view_handler(
        {"type": "view_submission", "callback_id": "modal"}, callback
    )
    context.register_slack_message_observer(callback)

    monkeypatch.setattr(manager, "_discover_and_load_inner", lambda: None)
    manager._discovered = True
    manager.discover_and_load(force=True)

    assert manager.get_slack_action_handlers() == []
    assert manager.get_slack_view_handlers() == []
    assert manager.get_slack_message_observers() == []


@pytest.mark.asyncio
async def test_connect_wires_plugin_modal_handler_and_wraps_failures():
    registered_views: list[tuple[dict, object]] = []

    def decorator(_matcher):
        def register(fn):
            return fn
        return register

    def register_view(matcher):
        def register(fn):
            registered_views.append((matcher, fn))
            return fn
        return register

    app = MagicMock()
    app.event = decorator
    app.command = decorator
    app.action = decorator
    app.view = register_view
    app.client = AsyncMock()

    client = AsyncMock()
    client.auth_test = AsyncMock(
        return_value={
            "user_id": "U_BOT",
            "user": "hermes",
            "team_id": "T_TEST",
            "team": "Test",
        }
    )

    async def broken_view(ack, body, view):
        if body.get("ack_first"):
            await ack()
        raise SystemExit("plugin bug")

    manager = MagicMock()
    manager.get_slack_action_handlers.return_value = []
    manager.get_slack_view_handlers.return_value = [
        (
            {"type": "view_submission", "callback_id": "triage_edit_submit"},
            broken_view,
            "triage",
        )
    ]

    adapter = SlackAdapter(PlatformConfig(enabled=True, token="xoxb-test"))
    with (
        patch.object(slack_mod, "SLACK_AVAILABLE", True),
        patch.object(slack_mod, "AsyncApp", return_value=app),
        patch.object(slack_mod, "AsyncWebClient", return_value=client),
        patch.object(slack_mod, "AsyncSocketModeHandler", return_value=MagicMock()),
        patch.dict(os.environ, {"SLACK_APP_TOKEN": "xapp-test"}),
        patch("gateway.status.acquire_scoped_lock", return_value=(True, None)),
        patch("gateway.status.release_scoped_lock"),
        patch("hermes_cli.plugins.get_plugin_manager", return_value=manager),
        patch.object(adapter, "_start_socket_mode_handler"),
        patch.object(adapter, "_ensure_socket_watchdog"),
    ):
        assert await adapter.connect() is True

    assert [matcher for matcher, _ in registered_views] == [
        {"type": "view_submission", "callback_id": "triage_edit_submit"}
    ]

    fallback_ack = AsyncMock()
    await registered_views[0][1](fallback_ack, {}, {})
    fallback_ack.assert_awaited_once()

    plugin_ack = AsyncMock()
    await registered_views[0][1](plugin_ack, {"ack_first": True}, {})
    plugin_ack.assert_awaited_once()
