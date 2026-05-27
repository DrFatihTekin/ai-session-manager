"""Compatibility wrapper for the legacy `copilot-session` entrypoint."""

from __future__ import annotations

from ai_session_manager.wrapper import run as _run


def run() -> None:
    """Run the Copilot wrapper through ai-session-manager."""
    _run("copilot")
