"""Hard process-level MCP isolation for management-only Dashboard servers."""

from __future__ import annotations

import argparse
import os
import sys
import types
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


def _dashboard_args(**overrides):
    defaults = {
        "status": False,
        "stop": False,
        "host": "127.0.0.1",
        "port": 9119,
        "no_open": True,
        "insecure": False,
        "skip_build": True,
        "isolated": False,
        "open_profile": "",
        "no_mcp": True,
        "headless_backend": False,
        "ssh_owner_nonce": None,
        "ssh_session_token_file": None,
    }
    defaults.update(overrides)
    return types.SimpleNamespace(**defaults)


def test_dashboard_parser_accepts_management_only_flag():
    from hermes_cli.subcommands.dashboard import build_dashboard_parser

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    build_dashboard_parser(
        subparsers,
        cmd_dashboard=lambda _args: None,
        cmd_dashboard_register=lambda _args: None,
    )

    args = parser.parse_args(["dashboard", "--no-mcp"])

    assert args.no_mcp is True


def test_dashboard_no_mcp_sets_guard_and_skips_startup_discovery(monkeypatch):
    import hermes_cli.main as main_mod

    calls = []
    monkeypatch.delenv("HERMES_MCP_DISABLED", raising=False)
    monkeypatch.delenv("HERMES_DESKTOP", raising=False)
    monkeypatch.delenv("HERMES_WEB_DIST", raising=False)
    monkeypatch.setattr(
        "hermes_cli.profiles.get_active_profile_name", lambda: "default"
    )
    monkeypatch.setattr(main_mod, "_sync_bundled_skills_quietly", lambda: None)
    monkeypatch.setattr(main_mod, "_maybe_setup_dashboard_auth_interactively", lambda _args: None)
    monkeypatch.setattr("hermes_cli.config.apply_terminal_config_to_env", lambda: None)
    monkeypatch.setattr("hermes_cli.plugins.discover_plugins", lambda: None)
    monkeypatch.setattr(
        "hermes_cli.mcp_startup.start_background_mcp_discovery",
        lambda **_kwargs: calls.append("discover"),
    )
    monkeypatch.setitem(
        sys.modules,
        "hermes_cli.web_server",
        types.SimpleNamespace(start_server=lambda **_kwargs: calls.append("server")),
    )

    try:
        main_mod.cmd_dashboard(_dashboard_args())

        assert os.environ["HERMES_MCP_DISABLED"] == "1"
        assert calls == ["server"]
    finally:
        # cmd_dashboard intentionally marks the long-lived process. This unit
        # test shares a process with unrelated MCP tests, so clear the marker.
        os.environ.pop("HERMES_MCP_DISABLED", None)


def test_process_level_mcp_disable_skips_config_and_connections(monkeypatch):
    monkeypatch.setenv("HERMES_MCP_DISABLED", "1")
    with patch("tools.mcp_tool._MCP_AVAILABLE", True), patch(
        "tools.mcp_tool._load_mcp_config"
    ) as load_config:
        from tools.mcp_tool import discover_mcp_tools

        result = discover_mcp_tools()

    assert result == []
    load_config.assert_not_called()


def test_process_level_mcp_disable_blocks_direct_registration_and_lazy_connect(
    monkeypatch,
):
    monkeypatch.setenv("HERMES_MCP_DISABLED", "1")
    from tools import mcp_tool

    with patch.object(mcp_tool, "_resolve_server_lazy") as resolve_lazy, patch.object(
        mcp_tool, "_run_on_mcp_loop"
    ) as run_on_loop:
        registered = mcp_tool.register_mcp_servers(
            {"bypass": {"url": "https://mcp.example/mcp", "lazy": True}}
        )
        connected = mcp_tool._ensure_lazy_server_connected("bypass")

    assert registered == []
    assert connected is False
    resolve_lazy.assert_not_called()
    run_on_loop.assert_not_called()


@pytest.mark.asyncio
async def test_process_level_mcp_disable_blocks_low_level_connection(monkeypatch):
    monkeypatch.setenv("HERMES_MCP_DISABLED", "1")
    from tools.mcp_tool import MCPServerTask

    task = MCPServerTask("blocked")

    async def fake_run(_config):
        task._ready.set()

    with patch.object(
        MCPServerTask, "run", new_callable=AsyncMock, side_effect=fake_run
    ) as run:
        with pytest.raises(RuntimeError, match="disabled for this process"):
            await task.start({"url": "https://mcp.example/mcp"})
    run.assert_not_awaited()


def _client(web_server) -> TestClient:
    client = TestClient(web_server.app)
    client.headers[web_server._SESSION_HEADER_NAME] = web_server._SESSION_TOKEN
    return client


def test_no_mcp_dashboard_blocks_every_mcp_http_route(monkeypatch):
    from hermes_cli import web_server

    monkeypatch.setenv("HERMES_MCP_DISABLED", "1")
    web_server.app.state.auth_required = False
    client = _client(web_server)

    requests = [
        client.get("/api/mcp/servers"),
        client.post("/api/mcp/_blocked"),
        client.delete("/api/mcp/_blocked"),
        client.get("/api/mcp/oauth/callback/notion?code=blocked&state=blocked"),
    ]

    assert {response.status_code for response in requests} == {409}
    assert all("disabled in this Dashboard process" in response.text for response in requests)


def test_no_mcp_gate_precedes_dashboard_auth(monkeypatch):
    from hermes_cli import web_server

    monkeypatch.setenv("HERMES_MCP_DISABLED", "1")
    web_server.app.state.auth_required = True
    try:
        response = TestClient(web_server.app).get("/api/mcp/servers")
    finally:
        web_server.app.state.auth_required = False

    assert response.status_code == 409
    assert "disabled in this Dashboard process" in response.text


def test_no_mcp_dashboard_keeps_management_ui_available(monkeypatch):
    from hermes_cli import web_server

    monkeypatch.setenv("HERMES_MCP_DISABLED", "1")
    web_server.app.state.auth_required = False

    response = _client(web_server).get("/api/status")

    assert response.status_code == 200
