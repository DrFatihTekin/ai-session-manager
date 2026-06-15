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
    new_session_args: tuple[str, ...] = ()
    resume_args: tuple[str, ...] = ()
    explicit_resume_args: tuple[str, ...] = ()
    bypass_flags: frozenset[str] = frozenset()
    passthrough_commands: frozenset[str] = frozenset()


TOOLS = {
    "agy": ToolSpec(
        key="agy",
        binary_name="agy",
        display_name="Antigravity CLI",
        session_mode="auto-resume",
        resume_args=("-c",),
        explicit_resume_args=("--conversation",),
        bypass_flags=frozenset({"-c", "--continue", "--conversation"}),
        passthrough_commands=frozenset({"auth"}),
    ),
    "claude": ToolSpec(
        key="claude",
        binary_name="claude",
        display_name="Claude Code",
        session_mode="managed-id",
        new_session_args=("--session-id",),
        resume_args=("-c",),
        explicit_resume_args=("-r",),
        bypass_flags=frozenset({"-c", "--continue", "-r", "--resume", "--session-id"}),
        passthrough_commands=frozenset({"agents", "attach", "auth", "install", "update"}),
    ),
    "codex": ToolSpec(
        key="codex",
        binary_name="codex",
        display_name="Codex",
        session_mode="auto-resume",
        resume_args=("resume", "--last"),
        explicit_resume_args=("resume",),
        passthrough_commands=frozenset(
            {"app", "debug", "exec", "mcp", "resume", "review", "sandbox"}
        ),
    ),
    "copilot": ToolSpec(
        key="copilot",
        binary_name="copilot",
        display_name="GitHub Copilot CLI",
        session_mode="managed-id",
        new_session_args=("--session-id",),
        bypass_flags=frozenset(
            {"--session-id", "--resume", "--continue", "--clear", "-p", "--prompt"}
        ),
        passthrough_commands=frozenset({"update"}),
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
        return git_root, git_root / f".{STATE_DIR_NAME}", "repo"
    return scope_dir, scope_dir / f".{STATE_DIR_NAME}", "folder"


def _state_file(tool_key: str, cwd: Path | None = None) -> tuple[Path, Path, str]:
    """Return the scope directory, tool state path, and scope kind."""
    scope_dir, state_root, scope_kind = _state_root(cwd)
    return scope_dir, state_root / f"{tool_key}.json", scope_kind


def _legacy_repo_state_file(tool_key: str, cwd: Path | None = None) -> Path | None:
    """Return the previous repo-only state file path, if applicable."""
    scope_dir = (cwd or Path.cwd()).resolve()
    git_root = _git_root(scope_dir)
    if git_root is None:
        return None
    return git_root / ".git" / STATE_DIR_NAME / f"{tool_key}.json"


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

    legacy_repo_path = _legacy_repo_state_file(spec.key, cwd)
    if legacy_repo_path is not None and legacy_repo_path.exists():
        payload = json.loads(legacy_repo_path.read_text())
        _write_state(path, payload)
        return payload

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


def _resume_invocation(
    spec: ToolSpec,
    state: dict[str, object],
    user_args: list[str],
    cwd: Path | None = None,
) -> list[str]:
    resume_target = state.get("resume_target")

    if spec.key == "claude" and isinstance(resume_target, str):
        if _claude_session_file(resume_target, cwd).exists():
            return [*spec.explicit_resume_args, resume_target, *user_args]
        print(
            f"[ai-session-manager] Stored Claude session {resume_target} is missing; "
            "falling back to Claude's latest-session resume."
        )
        return [*spec.resume_args, *user_args]

    if spec.session_mode == "managed-id":
        resume_target = state["resume_target"]
        if spec.explicit_resume_args:
            return [*spec.explicit_resume_args, str(resume_target), *user_args]
        return [*spec.new_session_args, str(resume_target), *user_args]

    if spec.key in {"agy", "codex"} and isinstance(resume_target, str):
        return [*spec.explicit_resume_args, str(resume_target), *user_args]

    return [*spec.resume_args, *user_args]


def _new_session_invocation(spec: ToolSpec, state: dict[str, object], user_args: list[str]) -> list[str]:
    resume_target = state.get("resume_target")
    if isinstance(resume_target, str) and spec.new_session_args:
        return [*spec.new_session_args, resume_target, *user_args]
    return user_args


def _claude_project_dir(cwd: Path | None = None) -> Path:
    scope_dir = (cwd or Path.cwd()).resolve()
    project_key = str(scope_dir).replace("\\", "-").replace("/", "-").replace(":", "-")
    return Path.home() / ".claude" / "projects" / project_key


def _claude_session_file(session_id: str, cwd: Path | None = None) -> Path:
    return _claude_project_dir(cwd) / f"{session_id}.jsonl"


def _codex_latest_session_id(cwd: Path | None = None) -> str | None:
    sessions_root = Path.home() / ".codex" / "sessions"
    if not sessions_root.exists():
        return None

    scope_dir = str((cwd or Path.cwd()).resolve())
    matches: list[tuple[float, str]] = []
    for path in sessions_root.glob("**/*.jsonl"):
        try:
            lines = path.read_text().splitlines()
        except OSError:
            continue
        for line in lines:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                break
            if record.get("type") != "session_meta":
                continue
            payload = record.get("payload", {})
            if not isinstance(payload, dict):
                break
            session_id = payload.get("id")
            session_cwd = payload.get("cwd")
            if (
                isinstance(session_id, str)
                and session_cwd == scope_dir
                and _codex_session_in_history(session_id)
            ):
                matches.append((path.stat().st_mtime, session_id))
            break

    if not matches:
        return None
    return max(matches)[1]


def _codex_session_in_history(session_id: str) -> bool:
    history_path = Path.home() / ".codex" / "history.jsonl"
    if not history_path.exists():
        return False

    try:
        lines = history_path.read_text().splitlines()
    except OSError:
        return False

    for line in lines:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("session_id") == session_id:
            return True
    return False


def _agy_latest_conversation_id(cwd: Path | None = None) -> str | None:
    history_path = Path.home() / ".gemini" / "antigravity-cli" / "history.jsonl"
    if not history_path.exists():
        return None

    scope_dir = str((cwd or Path.cwd()).resolve())
    try:
        lines = history_path.read_text().splitlines()
    except OSError:
        return None

    latest_display: str | None = None
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("workspace") != scope_dir:
            continue
        conversation_id = record.get("conversationId")
        if isinstance(conversation_id, str) and conversation_id:
            return conversation_id
        display = record.get("display")
        if isinstance(display, str) and display.strip():
            latest_display = display.strip()
            break

    if latest_display is None:
        return None

    brain_root = Path.home() / ".gemini" / "antigravity-cli" / "brain"
    if not brain_root.exists():
        return None

    for brain_dir in sorted(brain_root.glob("*"), key=lambda path: path.stat().st_mtime, reverse=True):
        user_request = _agy_first_user_request(brain_dir)
        if user_request == latest_display:
            return brain_dir.name
    return None


def _agy_conversation_exists(conversation_id: str, cwd: Path | None = None) -> bool:
    history_path = Path.home() / ".gemini" / "antigravity-cli" / "history.jsonl"
    if not history_path.exists():
        return False

    scope_dir = str((cwd or Path.cwd()).resolve())
    try:
        lines = history_path.read_text().splitlines()
    except OSError:
        return False

    for line in lines:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("workspace") != scope_dir:
            continue
        if record.get("conversationId") == conversation_id:
            return True
    return False


def _agy_first_user_request(brain_dir: Path) -> str | None:
    transcript = brain_dir / ".system_generated" / "logs" / "transcript_full.jsonl"
    if not transcript.exists():
        transcript = brain_dir / ".system_generated" / "logs" / "transcript.jsonl"
    if not transcript.exists():
        return None

    try:
        lines = transcript.read_text().splitlines()
    except OSError:
        return None

    for line in lines:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("type") != "USER_INPUT":
            continue
        return _extract_user_request(record.get("content"))
    return None


def _extract_user_request(content: object) -> str | None:
    if not isinstance(content, str):
        return None
    start = "<USER_REQUEST>"
    end = "</USER_REQUEST>"
    if start not in content or end not in content:
        return None
    return content.split(start, 1)[1].split(end, 1)[0].strip()


def _discover_resume_target(spec: ToolSpec, cwd: Path | None = None) -> str | None:
    if spec.key == "codex":
        return _codex_latest_session_id(cwd)
    if spec.key == "agy":
        return _agy_latest_conversation_id(cwd)
    return None


def _resume_target_is_valid(spec: ToolSpec, resume_target: str, cwd: Path | None = None) -> bool:
    if spec.key == "codex":
        return _codex_session_in_history(resume_target)
    if spec.key == "agy":
        return _agy_conversation_exists(resume_target, cwd)
    return True


def _exec(real: str, args: list[str]) -> None:
    """Replace the current process with the real tool (Unix) or spawn it (Windows)."""
    if IS_WINDOWS:
        result = subprocess.run([real] + args)
        sys.exit(result.returncode)
    os.execv(real, [real] + args)


def _invoke_tool(
    spec: ToolSpec,
    real: str,
    args: list[str],
    cwd: Path,
    state: dict[str, object] | None = None,
) -> None:
    if spec.key in {"agy", "codex"}:
        result = subprocess.run([real] + args)
        if result.returncode == 0:
            resume_target = _discover_resume_target(spec, cwd)
            if resume_target is not None:
                _, state_path, _ = _state_file(spec.key, cwd)
                _write_state(state_path, _state_payload(spec, resume_target))
        sys.exit(result.returncode)

    _exec(real, args)


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
    real_from_env = os.environ.get(REAL_BIN_ENV)
    if real_from_env and Path(real_from_env).exists() and os.access(real_from_env, os.X_OK):
        real = real_from_env
    else:
        real = _find_real_binary(spec)
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
            _invoke_tool(spec, real, _new_session_invocation(spec, state, user_args), scope_dir, state)
            return

        print(
            f"[ai-session-manager] Starting new {spec.display_name} session ({scope_dir.name})",
            flush=True,
        )
        _invoke_tool(spec, real, user_args, scope_dir, state)
        return

    if "resume_target" not in state:
        resume_target = _discover_resume_target(spec, scope_dir)
        if resume_target is not None:
            state = _state_payload(spec, resume_target)
            _, state_path, _ = _state_file(spec.key, scope_dir)
            _write_state(state_path, state)
    elif spec.key in {"agy", "codex"}:
        resume_target = str(state["resume_target"])
        if not _resume_target_is_valid(spec, resume_target, scope_dir):
            refreshed_target = _discover_resume_target(spec, scope_dir)
            if refreshed_target is not None and refreshed_target != resume_target:
                state = _state_payload(spec, refreshed_target)
            else:
                state = _state_payload(spec)
            _, state_path, _ = _state_file(spec.key, scope_dir)
            _write_state(state_path, state)

    if spec.session_mode == "managed-id":
        session_id = str(state["resume_target"])
        print(f"[ai-session-manager] Resuming session {session_id} ({scope_dir.name})", flush=True)
    elif "resume_target" in state:
        session_id = str(state["resume_target"])
        print(f"[ai-session-manager] Resuming session {session_id} ({scope_dir.name})", flush=True)
    else:
        print(
            f"[ai-session-manager] Resuming latest {spec.display_name} session ({scope_dir.name})",
            flush=True,
        )

    _invoke_tool(spec, real, _resume_invocation(spec, state, user_args, scope_dir), scope_dir, state)
    return
