"""Fail-closed Windows gateway release preflight."""

from __future__ import annotations

from pathlib import Path

import pytest

from hermes_cli import gateway_windows


def test_start_runs_preflight_before_spawn(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(gateway_windows, "_assert_windows", lambda: None)
    monkeypatch.setattr(gateway_windows, "_gateway_pids", lambda: [])
    monkeypatch.setattr(
        gateway_windows,
        "_run_configured_gateway_preflight",
        lambda: calls.append("preflight"),
    )
    monkeypatch.setattr(gateway_windows, "is_task_registered", lambda: False)
    monkeypatch.setattr(gateway_windows, "is_startup_entry_installed", lambda: True)
    monkeypatch.setattr(
        gateway_windows,
        "_spawn_detached",
        lambda: (calls.append("spawn"), 999)[1],
    )
    monkeypatch.setattr(
        gateway_windows, "_report_gateway_start", lambda _detail: None
    )

    gateway_windows.start()

    assert calls == ["preflight", "spawn"]


def test_start_does_not_preflight_when_gateway_is_already_running(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(gateway_windows, "_assert_windows", lambda: None)
    monkeypatch.setattr(gateway_windows, "_gateway_pids", lambda: [1234])
    monkeypatch.setattr(
        gateway_windows,
        "_run_configured_gateway_preflight",
        lambda: calls.append("preflight"),
    )

    gateway_windows.start()

    assert calls == []


def test_restart_verifies_preflight_before_stopping(monkeypatch):
    calls: list[object] = []
    monkeypatch.setattr(gateway_windows, "_assert_windows", lambda: None)
    monkeypatch.setattr(
        gateway_windows,
        "_run_configured_gateway_preflight",
        lambda: calls.append("preflight"),
        raising=False,
    )
    monkeypatch.setattr(gateway_windows, "stop", lambda: calls.append("stop"))
    monkeypatch.setattr(gateway_windows, "_wait_for_gateway_absent", lambda **_kw: True)
    monkeypatch.setattr(gateway_windows.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        gateway_windows,
        "start",
        lambda *, _preflight_verified=False: calls.append(
            ("start", _preflight_verified)
        ),
    )
    monkeypatch.setattr(gateway_windows, "_wait_for_gateway_ready", lambda **_kw: True)

    gateway_windows.restart()

    assert calls == ["preflight", "stop", ("start", True)]


def test_failed_preflight_preserves_running_gateway(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(gateway_windows, "_assert_windows", lambda: None)

    def fail():
        raise RuntimeError("candidate incompatible")

    monkeypatch.setattr(
        gateway_windows, "_run_configured_gateway_preflight", fail, raising=False
    )
    monkeypatch.setattr(gateway_windows, "stop", lambda: calls.append("stop"))
    # Keep the RED-path test side-effect free even if production has not yet
    # implemented the preflight call.
    monkeypatch.setattr(gateway_windows, "_wait_for_gateway_absent", lambda **_kw: True)
    monkeypatch.setattr(gateway_windows.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(gateway_windows, "start", lambda **_kw: calls.append("start"))
    monkeypatch.setattr(gateway_windows, "_wait_for_gateway_ready", lambda **_kw: True)

    with pytest.raises(RuntimeError, match="candidate incompatible"):
        gateway_windows.restart()
    assert calls == []


def test_start_runs_preflight_before_detached_spawn(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(gateway_windows, "_assert_windows", lambda: None)
    monkeypatch.setattr(gateway_windows, "_gateway_pids", lambda: [])
    monkeypatch.setattr(
        gateway_windows,
        "_run_configured_gateway_preflight",
        lambda: calls.append("preflight"),
        raising=False,
    )
    monkeypatch.setattr(gateway_windows, "is_task_registered", lambda: True)
    monkeypatch.setattr(gateway_windows, "is_startup_entry_installed", lambda: False)
    monkeypatch.setattr(
        gateway_windows, "_spawn_detached", lambda: calls.append("spawn") or 123
    )
    monkeypatch.setattr(gateway_windows, "_report_gateway_start", lambda _detail: None)

    gateway_windows.start()

    assert calls == ["preflight", "spawn"]


def test_configured_preflight_runs_only_script_under_hermes_home(monkeypatch, tmp_path):
    home = tmp_path / "home"
    script = home / "scripts" / "preflight.py"
    sentinel = tmp_path / "ran"
    script.parent.mkdir(parents=True)
    script.write_text(
        f"from pathlib import Path\nPath({str(sentinel)!r}).write_text('yes')\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("hermes_cli.config.get_hermes_home", lambda: home)
    monkeypatch.setattr(
        "hermes_cli.config.load_config_readonly",
        lambda: {"gateway": {"preflight_script": str(script)}},
    )

    gateway_windows._run_configured_gateway_preflight()

    assert sentinel.read_text(encoding="utf-8") == "yes"


def test_preflight_rejects_script_outside_hermes_home(monkeypatch, tmp_path):
    home = tmp_path / "home"
    outside = tmp_path / "outside.py"
    home.mkdir()
    outside.write_text("raise SystemExit(0)\n", encoding="utf-8")
    monkeypatch.setattr("hermes_cli.config.get_hermes_home", lambda: home)
    monkeypatch.setattr(
        "hermes_cli.config.load_config_readonly",
        lambda: {"gateway": {"preflight_script": str(outside)}},
    )

    with pytest.raises(RuntimeError, match="existing file under"):
        gateway_windows._run_configured_gateway_preflight()


def test_preflight_rejects_relative_script_path(monkeypatch, tmp_path):
    home = tmp_path / "home"
    (home / "scripts").mkdir(parents=True)
    monkeypatch.setattr("hermes_cli.config.get_hermes_home", lambda: home)
    monkeypatch.setattr(
        "hermes_cli.config.load_config_readonly",
        lambda: {"gateway": {"preflight_script": "scripts/preflight.py"}},
    )

    with pytest.raises(RuntimeError, match="must be an absolute path"):
        gateway_windows._run_configured_gateway_preflight()


def test_preflight_rejects_non_python_file(monkeypatch, tmp_path):
    home = tmp_path / "home"
    script = home / "scripts" / "preflight.sh"
    script.parent.mkdir(parents=True)
    script.write_text("exit 0\n", encoding="utf-8")
    monkeypatch.setattr("hermes_cli.config.get_hermes_home", lambda: home)
    monkeypatch.setattr(
        "hermes_cli.config.load_config_readonly",
        lambda: {"gateway": {"preflight_script": str(script)}},
    )

    with pytest.raises(RuntimeError, match="must name a Python file"):
        gateway_windows._run_configured_gateway_preflight()


def test_preflight_timeout_fails_closed(monkeypatch, tmp_path):
    home = tmp_path / "home"
    script = home / "scripts" / "preflight.py"
    script.parent.mkdir(parents=True)
    script.write_text("import time\ntime.sleep(10)\n", encoding="utf-8")
    monkeypatch.setattr("hermes_cli.config.get_hermes_home", lambda: home)
    monkeypatch.setattr(
        "hermes_cli.config.load_config_readonly",
        lambda: {"gateway": {"preflight_script": str(script)}},
    )
    monkeypatch.setattr(gateway_windows, "_GATEWAY_PREFLIGHT_TIMEOUT_S", 0.01)

    with pytest.raises(RuntimeError, match="timed out after 0.01s"):
        gateway_windows._run_configured_gateway_preflight()


def test_preflight_failure_reports_stdout_and_stderr(monkeypatch, tmp_path):
    home = tmp_path / "home"
    script = home / "scripts" / "preflight.py"
    script.parent.mkdir(parents=True)
    script.write_text(
        "import sys\nprint('progress')\nprint('actual failure', file=sys.stderr)\n"
        "raise SystemExit(7)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("hermes_cli.config.get_hermes_home", lambda: home)
    monkeypatch.setattr(
        "hermes_cli.config.load_config_readonly",
        lambda: {"gateway": {"preflight_script": str(script)}},
    )

    with pytest.raises(RuntimeError) as exc_info:
        gateway_windows._run_configured_gateway_preflight()

    detail = str(exc_info.value)
    assert "failed (7)" in detail
    assert "progress" in detail
    assert "actual failure" in detail
