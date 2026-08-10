"""Turn-end guard for kanban workers, which must end with ``kanban_complete`` or
``kanban_block``. Some models narrate the next step and stop with no tool calls;
Hermes treats that as a clean exit → ``rc=0`` → dispatcher ``protocol_violation``.
Policy-only: return a bounded synthetic nudge so the loop continues instead of exiting.
"""

from __future__ import annotations

import json
import os
from typing import Any, Iterable, Optional


_TERMINAL_KANBAN_TOOLS = frozenset({"kanban_complete", "kanban_block"})
_HANDOFF_KANBAN_TOOLS = frozenset({
    "kanban_escalate_to_default",
    "mcp__kanban_escalation__kanban_escalate_to_default",
})
_SUCCESSFUL_HANDOFF_STATUSES = frozenset({"escalated", "already_escalated"})

_DEFAULT_MAX_ATTEMPTS = 2


def kanban_stop_nudge_enabled() -> bool:
    """On when ``HERMES_KANBAN_TASK`` is set, unless ``HERMES_KANBAN_STOP_NUDGE`` disables it."""
    if (os.environ.get("HERMES_KANBAN_STOP_NUDGE") or "").strip().lower() in {"0", "false", "no", "off"}:
        return False
    return bool((os.environ.get("HERMES_KANBAN_TASK") or "").strip())


def _tool_call_name(tc: Any) -> str:
    """Tool name from a dict or object tool call (``function.name`` first, then ``name``)."""
    if isinstance(tc, dict):
        fn = tc.get("function")
        return str((fn.get("name") if isinstance(fn, dict) else tc.get("name")) or "")
    fn = getattr(tc, "function", None)
    return str((getattr(fn, "name", "") if fn is not None else getattr(tc, "name", "")) or "")


def _tool_call_id(tc: Any) -> str:
    if isinstance(tc, dict):
        return str(tc.get("id") or tc.get("call_id") or "")
    return str(getattr(tc, "id", "") or getattr(tc, "call_id", "") or "")


def _successful_handoff_result(content: Any) -> bool:
    """True only for a persisted successful specialist handoff response."""
    payload = content
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (TypeError, json.JSONDecodeError):
            return False
    if isinstance(payload, dict):
        if payload.get("isError") is True or payload.get("error"):
            return False
        status = str(payload.get("status") or "")
        if status in _SUCCESSFUL_HANDOFF_STATUSES:
            return True
        if status.lower() in {"error", "failed", "failure"}:
            return False
        for key in ("result", "content"):
            if key in payload and _successful_handoff_result(payload[key]):
                return True
        return False
    if isinstance(payload, list):
        return any(_successful_handoff_result(item) for item in payload)
    return False


def session_called_kanban_terminal(messages: Iterable[dict] | None) -> bool:
    """True if this conversation already invoked a terminal kanban tool.

    A *successful* specialist handoff also ends the turn: the worker has given the task away, so
    demanding kanban_complete/kanban_block from it would be a protocol violation it cannot satisfy.
    """
    handoff_call_ids: set[str] = set()
    for msg in filter(lambda m: isinstance(m, dict), messages or ()):
        role = msg.get("role")
        if role == "assistant":
            for tc in msg.get("tool_calls") or []:
                name = _tool_call_name(tc)
                if name in _TERMINAL_KANBAN_TOOLS:
                    return True
                if name in _HANDOFF_KANBAN_TOOLS:
                    call_id = _tool_call_id(tc)
                    if call_id:
                        handoff_call_ids.add(call_id)
        elif role == "tool":
            name = str(msg.get("name") or "")
            if name in _TERMINAL_KANBAN_TOOLS:
                return True
            call_id = str(msg.get("tool_call_id") or msg.get("call_id") or "")
            if (name in _HANDOFF_KANBAN_TOOLS or call_id in handoff_call_ids) and (
                _successful_handoff_result(msg.get("content"))
            ):
                return True
    return False


def build_kanban_stop_nudge(
    *,
    messages: Iterable[dict] | None = None,
    attempts: int = 0,
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
    task_id: Optional[str] = None,
) -> Optional[str]:
    """Synthetic follow-up when a kanban worker exits without a terminal tool; ``None`` when
    the guard should not fire (not a kanban worker, already completed/blocked, budget exhausted)."""
    if (
        not kanban_stop_nudge_enabled()
        or attempts >= max_attempts
        or session_called_kanban_terminal(messages)
    ):
        return None

    tid = (task_id or os.environ.get("HERMES_KANBAN_TASK") or "").strip() or "this task"
    return (
        "[System: You are a Hermes kanban worker. A plain-text reply is NOT a "
        "terminal state for the board.\n\n"
        f"Task `{tid}` is still `running`. Ending now without a board tool "
        "causes a protocol violation (clean exit with no "
        "`kanban_complete` / `kanban_block`).\n\n"
        "Do this immediately in your next response — do not narrate intent:\n"
        "1. Finish any remaining deliverable (write the required file(s) now).\n"
        "2. Call `kanban_complete(summary=..., artifacts=[...])` if the work "
        "is done, OR `kanban_block(reason=...)` if you are blocked.\n\n"
        "Never end a turn with only a promise of future action. Repeated "
        "protocol violations will block this task and require manual intervention.]"
    )


__all__ = ["build_kanban_stop_nudge", "kanban_stop_nudge_enabled", "session_called_kanban_terminal"]
