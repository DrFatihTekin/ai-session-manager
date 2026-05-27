"""Compatibility CLI for the legacy `copilot-session` command."""

from __future__ import annotations

import argparse
import sys

from ai_session_manager import cli as manager_cli


def _copilot_args() -> argparse.Namespace:
    return argparse.Namespace(tools=["copilot"])


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="copilot-session",
        description="Compatibility wrapper for ai-session-manager limited to Copilot.",
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    sub.add_parser("setup", help="Install the Copilot wrapper")
    sub.add_parser("teardown", help="Remove the Copilot wrapper and restore the original binary")
    sub.add_parser("status", help="Show the Copilot wrapper status")
    sub.add_parser("reset", help="Delete Copilot state for the current repo or folder")

    args = parser.parse_args()

    dispatch = {
        "setup": manager_cli.cmd_setup,
        "teardown": manager_cli.cmd_teardown,
        "status": manager_cli.cmd_status,
        "reset": manager_cli.cmd_reset,
    }

    if args.command not in dispatch:
        parser.print_help()
        sys.exit(0)

    sys.exit(dispatch[args.command](_copilot_args()))
