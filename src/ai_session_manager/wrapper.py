"""Core wrapper logic for supported AI CLI tools."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import platform
import subprocess
import sys
import uuid
from pathlib import Path


IS_WINDOWS = platform.system() == "Windows"
STATE_DIR_NAME = "ai-session-manager"
LEGACY_REPO_SESSION_FILE = "copilot-session"
LEGACY_FOLDER_SESSION_FILE = ".copilot-session"
REAL_BIN_ENV = "AI_SESSION_MANAGER_REAL_BIN"
TOOL_KEY_ENV = "AI_SESSION_MANAGER_TOOL"


@dataclass(frozen=True)
class ToolSpec:
    key: str
    binary_name: str
    display_name: str
    session_mode: str
    resume_args: tuple[str, ...] = ()
    bypass_flags: frozenset[str] = frozenset()
    passthrough_commands: frozenset[str] = frozenset()


TOOLS = {
    "agy": ToolSpec(
        key="agy",
        binary_name="agy",
        display_name="Antigravity CLI",
        session_mode="auto-resume",
        resume_args=("-c",),
        bypass_flags=frozenset({"-c", "--conversation"}),
        passthrough_commands=frozenset({"auth"}),
    ),
    "claude": ToolSpec(
        key="claude",
        binary_name="claude",
        display_name="Claude Code",
        session_mode="auto-resume",
        resume_args=("-c",),
        bypass_flags=frozenset({"-c", "--continue", "-r", "--resume"}),
        passthrough_commands=frozenset({"agents", "attach", "auth", "install", "update"}),
    ),
    "codex": ToolSpec(
        key="codex",
        binary_name="codex",
        display_name="Codex",
        session_mode="auto-resume",
        resume_args=("resume", "--last"),
        passthrough_commands=frozenset(
            {"app", "debug", "exec", "mcp", "resume", "review", "sandbox"}
        ),
    ),
    "copilot": ToolSpec(
        key="copilot",
        binary_name="copilot",
        display_name="GitHub Copilot CLI",
        session_mode="managed-id",
        bypass_flags=frozenset(
            {"--session-id", "--resume", "--continue", "--clear", "-p", "--prompt"}
        ),
        passthrough_commands=frozenset({"update"}),
    ),
    "gemini": ToolSpec(
        key="gemini",
        binary_name="gemini",
        display_name="Gemini CLI",
        session_mode="auto-resume",
        resume_args=("--resume",),
        bypass_flags=frozenset({"-r", "--resume", "--list-sessions", "--delete-session"}),
    ),
}

UNIVERSAL_BYPASS_FLAGS = frozenset({"-h", "--help", "-V", "--version"})


def get_tool(tool_key: str) -> ToolSpec:
    try:
        return TOOLS[tool_key]
    except KeyError as exc:
        raise ValueError(f"Unsupported tool: {tool_key}") from exc


def _git_root(cwd: Path | None = None) -> Path | None:
    """Return the root of the current git repo, or None if not in one."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            cwd=cwd,
        )
    except FileNotFoundError:
        return None

    if result.returncode == 0:
        return Path(result.stdout.strip())
    return None


def _state_root(cwd: Path | None = None) -> tuple[Path, Path, str]:
    """Return the current scope directory, state root, and scope kind."""
    scope_dir = (cwd or Path.cwd()).resolve()
    git_root = _git_root(scope_dir)
    if git_root is not None:
        return git_root, git_root / ".git" / STATE_DIR_NAME, "repo"
    return scope_dir, scope_dir / f".{STATE_DIR_NAME}", "folder"


def _state_file(tool_key: str, cwd: Path | None = None) -> tuple[Path, Path, str]:
    """Return the scope directory, tool state path, and scope kind."""
    scope_dir, state_root, scope_kind = _state_root(cwd)
    return scope_dir, state_root / f"{tool_key}.json", scope_kind


def _legacy_copilot_session_file(cwd: Path | None = None) -> Path:
    """Return the pre-refactor Copilot state file path."""
    scope_dir = (cwd or Path.cwd()).resolve()
    git_root = _git_root(scope_dir)
    if git_root is not None:
        return git_root / ".git" / LEGACY_REPO_SESSION_FILE
    return scope_dir / LEGACY_FOLDER_SESSION_FILE


def _state_payload(spec: ToolSpec, resume_target: str | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "version": 1,
        "tool": spec.key,
        "session_mode": spec.session_mode,
    }
    if resume_target is not None:
        payload["resume_target"] = resume_target
    return payload


def _write_state(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def _load_state(spec: ToolSpec, cwd: Path | None = None) -> dict[str, object] | None:
    _, path, _ = _state_file(spec.key, cwd)
    if path.exists():
        return json.loads(path.read_text())

    if spec.key != "copilot":
        return None

    legacy_path = _legacy_copilot_session_file(cwd)
    if not legacy_path.exists():
        return None

    session_id = legacy_path.read_text().strip()
    if not session_id:
        return None

    payload = _state_payload(spec, session_id)
    _write_state(path, payload)
    return payload


def _create_state(spec: ToolSpec, cwd: Path | None = None) -> dict[str, object]:
    _, path, _ = _state_file(spec.key, cwd)
    resume_target = str(uuid.uuid4()) if spec.session_mode == "managed-id" else None
    payload = _state_payload(spec, resume_target)
    _write_state(path, payload)
    return payload


def _real_bin_name(spec: ToolSpec, wrapper_path: Path) -> Path:
    """Return the expected path of the real binary alongside the wrapper."""
    if IS_WINDOWS:
        return wrapper_path.parent / (wrapper_path.stem + "-real" + wrapper_path.suffix)
    return wrapper_path.parent / f"{spec.binary_name}-real"


def _find_real_binary(spec: ToolSpec) -> str:
    """
    Find the real tool binary by checking a sibling '<tool>-real' first, then PATH.
    """
    script_path = Path(sys.argv[0]).resolve()
    sibling = _real_bin_name(spec, script_path)
    if sibling.exists() and os.access(sibling, os.X_OK):
        return str(sibling)

    candidates = [f"{spec.binary_name}-real.exe", f"{spec.binary_name}-real"]
    if not IS_WINDOWS:
        candidates = [f"{spec.binary_name}-real"]

    for directory in os.environ.get("PATH", "").split(os.pathsep):
        for name in candidates:
            candidate = Path(directory) / name
            if candidate.exists() and os.access(candidate, os.X_OK):
                return str(candidate)

    raise FileNotFoundError(
        f"Cannot find '{spec.binary_name}-real'. Run 'ai-session-manager setup {spec.key}' first."
    )


def _first_positional_arg(args: list[str]) -> str | None:
    for arg in args:
        if arg == "--":
            return None
        if not arg.startswith("-") or arg == "-":
            return arg
    return None


def _should_bypass(spec: ToolSpec, args: list[str]) -> bool:
    for arg in args:
        base = arg.split("=", 1)[0]
        if base in UNIVERSAL_BYPASS_FLAGS or base in spec.bypass_flags:
            return True

    first_positional = _first_positional_arg(args)
    return first_positional in spec.passthrough_commands


def _resume_invocation(spec: ToolSpec, state: dict[str, object], user_args: list[str]) -> list[str]:
    if spec.session_mode == "managed-id":
        resume_target = state["resume_target"]
        return ["--session-id", str(resume_target), *user_args]
    return [*spec.resume_args, *user_args]


def _exec(real: str, args: list[str]) -> None:
    """Replace the current process with the real tool (Unix) or spawn it (Windows)."""
    if IS_WINDOWS:
        result = subprocess.run([real] + args)
        sys.exit(result.returncode)
    os.execv(real, [real] + args)


def _tool_from_invocation(tool_key: str | None) -> ToolSpec:
    if tool_key is not None:
        return get_tool(tool_key)

    env_tool = os.environ.get(TOOL_KEY_ENV)
    if env_tool:
        return get_tool(env_tool)

    script_name = Path(sys.argv[0]).stem
    return get_tool(script_name)


def run(tool_key: str | None = None) -> None:
    """Entry point for installed tool wrappers."""
    spec = _tool_from_invocation(tool_key)
    real = os.environ.get(REAL_BIN_ENV) or _find_real_binary(spec)
    user_args = sys.argv[1:]

    if _should_bypass(spec, user_args):
        _exec(real, user_args)
        return

    scope_dir, _, _scope_kind = _state_file(spec.key)
    state = _load_state(spec)

    if state is None:
        state = _create_state(spec)
        if spec.session_mode == "managed-id":
            session_id = str(state["resume_target"])
            print(f"[ai-session-manager] New session {session_id} ({scope_dir.name})", flush=True)
            _exec(real, _resume_invocation(spec, state, user_args))
            return

        print(
            f"[ai-session-manager] Starting new {spec.display_name} session ({scope_dir.name})",
            flush=True,
        )
        _exec(real, user_args)
        return

    if spec.session_mode == "managed-id":
        session_id = str(state["resume_target"])
        print(f"[ai-session-manager] Resuming session {session_id} ({scope_dir.name})", flush=True)
    else:
        print(
            f"[ai-session-manager] Resuming latest {spec.display_name} session ({scope_dir.name})",
            flush=True,
        )

    _exec(real, _resume_invocation(spec, state, user_args))
    return
