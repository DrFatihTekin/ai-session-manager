"""Core wrapper logic: resolve session ID for the current git repo and exec the real copilot."""

from __future__ import annotations

import os
import platform
import subprocess
import sys
import uuid
from pathlib import Path


SESSION_FILE = "copilot-session"  # stored inside .git/
IS_WINDOWS = platform.system() == "Windows"


def _git_root() -> Path | None:
    """Return the root of the current git repo, or None if not in one."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return Path(result.stdout.strip())
    except FileNotFoundError:
        pass
    return None


def _real_bin_name(wrapper_path: Path) -> Path:
    """Return the expected path of the real copilot binary alongside the wrapper."""
    if IS_WINDOWS:
        # copilot.exe → copilot-real.exe
        return wrapper_path.parent / (wrapper_path.stem + "-real" + wrapper_path.suffix)
    return wrapper_path.parent / "copilot-real"


def _find_real_copilot() -> str:
    """
    Find the real copilot binary.  Checks for a sibling 'copilot-real' (or
    'copilot-real.exe' on Windows) first, then searches PATH.
    Falls back to the COPILOT_REAL_BIN environment variable.
    """
    script_path = Path(sys.argv[0]).resolve()
    sibling = _real_bin_name(script_path)
    if sibling.exists() and os.access(sibling, os.X_OK):
        return str(sibling)

    # Search PATH for 'copilot-real' / 'copilot-real.exe'
    candidates = ["copilot-real.exe", "copilot-real"] if IS_WINDOWS else ["copilot-real"]
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        for name in candidates:
            candidate = Path(directory) / name
            if candidate.exists() and os.access(candidate, os.X_OK):
                return str(candidate)

    raise FileNotFoundError(
        "Cannot find 'copilot-real'. "
        "Run 'copilot-session setup' first, or set COPILOT_REAL_BIN in your environment."
    )


_BYPASS_FLAGS = frozenset([
    "--session-id", "--resume", "--continue", "--clear", "-p", "--prompt",
])


def _has_session_flag(args: list[str]) -> bool:
    for arg in args:
        base = arg.split("=")[0]
        if base in _BYPASS_FLAGS:
            return True
    return False


def _exec(real: str, args: list[str]) -> None:
    """Replace the current process with the real copilot (Unix) or spawn it (Windows)."""
    if IS_WINDOWS:
        # Windows doesn't support true exec — spawn and forward the exit code.
        result = subprocess.run([real] + args)
        sys.exit(result.returncode)
    else:
        os.execv(real, [real] + args)


def run() -> None:
    """Entry point for the copilot wrapper installed by `copilot-session setup`."""
    real = os.environ.get("COPILOT_REAL_BIN") or _find_real_copilot()
    user_args = sys.argv[1:]

    git_root = _git_root()

    if git_root and not _has_session_flag(user_args):
        session_file = git_root / ".git" / SESSION_FILE

        if session_file.exists():
            session_id = session_file.read_text().strip()
            print(f"[copilot-session] Resuming session {session_id} ({git_root.name})", flush=True)
        else:
            session_id = str(uuid.uuid4())
            session_file.write_text(session_id)
            print(f"[copilot-session] New session {session_id} ({git_root.name})", flush=True)

        _exec(real, ["--session-id", session_id] + user_args)
    else:
        _exec(real, user_args)
