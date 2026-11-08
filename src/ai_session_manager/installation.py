"""Shared wrapper locations and executable discovery."""

from __future__ import annotations

import os
import platform
from pathlib import Path


def wrapper_directory() -> Path:
    override = os.environ.get("AI_SESSION_MANAGER_BIN_DIR")
    if override:
        return Path(override).expanduser().absolute()
    if platform.system() == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
    return (base / "ai-session-manager" / "bin").expanduser().absolute()


def is_wrapper(path: Path) -> bool:
    try:
        with path.open("rb") as stream:
            return b"ai_session_manager.wrapper" in stream.read(4096)
    except OSError:
        return False


def find_original(name: str) -> Path | None:
    """Find a native executable in PATH, skipping all of our wrappers."""
    names = [name]
    if os.name == "nt":
        extensions = os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").split(";")
        names.extend(name + extension for extension in extensions if extension)
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        for executable in names:
            candidate = Path(directory or os.curdir) / executable
            if candidate.is_file() and os.access(candidate, os.X_OK) and not is_wrapper(candidate):
                return candidate.absolute()
    return None
