"""Session conversion helpers for supported AI CLI pairs."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess
import uuid

from ai_session_manager import wrapper


class SessionConversionError(ValueError):
    """Raised when a requested session conversion cannot be completed."""


@dataclass(frozen=True)
class TranscriptMessage:
    role: str
    content: str
    timestamp: str


@dataclass(frozen=True)
class ConversionResult:
    source_tool: str
    target_tool: str
    source_session: str
    target_session: str
    target_path: Path
    applied_state_path: Path | None
    message_count: int
    warnings: tuple[str, ...]


def _extract_text_content(items: object, item_type: str) -> str:
    if not isinstance(items, list):
        return ""

    parts: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("type") != item_type:
            continue
        text = item.get("text")
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())
    return "\n".join(parts)


def _resolve_source_session(
    source_tool: str,
    cwd: Path,
    source_session: str | None,
) -> str:
    if source_session:
        return source_session

    if source_tool != "copilot":
        raise SessionConversionError(
            f"{source_tool} -> claude requires --source-session explicitly. "
            f"{source_tool} wrapper state only tracks resume-latest behavior, not a stable session ID."
        )

    spec = wrapper.get_tool(source_tool)
    state = wrapper._load_state(spec, cwd)
    if not state or "resume_target" not in state:
        raise SessionConversionError(
            "No stored copilot session found for this project. "
            "Pass --source-session explicitly."
        )

    return str(state["resume_target"])


def _find_single_match(
    pattern: str,
    root: Path,
    description: str,
    source_session: str,
) -> Path:
    matches = sorted(root.glob(pattern))
    if not matches:
        raise SessionConversionError(
            f"Could not find {description} for source session {source_session} under {root}."
        )
    if len(matches) > 1:
        sample = ", ".join(str(path) for path in matches[:3])
        raise SessionConversionError(
            f"Source session {source_session} matched multiple {description} paths. "
            f"Pass a full path instead. Matches include: {sample}"
        )
    return matches[0]


def _copilot_events_path(home_dir: Path, session_id: str) -> Path:
    return home_dir / ".copilot" / "session-state" / session_id / "events.jsonl"


def _extract_copilot_transcript(
    home_dir: Path,
    session_id: str,
) -> tuple[list[TranscriptMessage], list[str]]:
    events_path = _copilot_events_path(home_dir, session_id)
    if not events_path.exists():
        raise SessionConversionError(
            f"Copilot session {session_id} was not found at {events_path}."
        )

    messages: list[TranscriptMessage] = []
    assistant_messages_with_tools = 0

    for line in events_path.read_text().splitlines():
        if not line.strip():
            continue

        event = json.loads(line)
        event_type = event.get("type")
        data = event.get("data", {})
        timestamp = str(event.get("timestamp", ""))

        if event_type == "user.message":
            content = data.get("content")
            if isinstance(content, str) and content.strip():
                messages.append(
                    TranscriptMessage(role="user", content=content, timestamp=timestamp)
                )
        elif event_type == "assistant.message":
            content = data.get("content")
            if isinstance(content, str) and content.strip():
                messages.append(
                    TranscriptMessage(
                        role="assistant",
                        content=content,
                        timestamp=timestamp,
                    )
                )
            tool_requests = data.get("toolRequests")
            if isinstance(tool_requests, list) and tool_requests:
                assistant_messages_with_tools += 1

    if not messages:
        raise SessionConversionError(
            f"Copilot session {session_id} did not contain any visible user/assistant messages."
        )

    warnings: list[str] = []
    if assistant_messages_with_tools:
        warnings.append(
            f"{assistant_messages_with_tools} Copilot assistant messages referenced tool calls. "
            "Visible chat history can be migrated, but Copilot tool requests and tool results are not transferable."
        )

    return messages, warnings


def _codex_session_id(path: Path) -> str | None:
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("type") != "session_meta":
            continue
        payload = record.get("payload", {})
        session_id = payload.get("id")
        if isinstance(session_id, str):
            return session_id
        break
    return None


def _resolve_codex_session_path(home_dir: Path, source_session: str) -> Path:
    direct_path = Path(source_session).expanduser()
    if direct_path.exists():
        return direct_path

    sessions_root = home_dir / ".codex" / "sessions"
    matches: list[Path] = []
    for path in sorted(sessions_root.glob("**/*.jsonl")):
        session_id = _codex_session_id(path)
        if session_id and session_id.startswith(source_session):
            matches.append(path)

    if not matches:
        raise SessionConversionError(
            f"Could not find Codex session {source_session} under {sessions_root}."
        )
    if len(matches) > 1:
        sample = ", ".join(str(path) for path in matches[:3])
        raise SessionConversionError(
            f"Source session {source_session} matched multiple Codex sessions. "
            f"Pass the full session ID or file path. Matches include: {sample}"
        )
    return matches[0]


def _extract_codex_transcript(
    home_dir: Path,
    source_session: str,
) -> tuple[list[TranscriptMessage], list[str]]:
    session_path = _resolve_codex_session_path(home_dir, source_session)
    messages: list[TranscriptMessage] = []
    tool_events = 0

    for line in session_path.read_text().splitlines():
        if not line.strip():
            continue

        record = json.loads(line)
        record_type = record.get("type")
        payload = record.get("payload", {})
        timestamp = str(record.get("timestamp", ""))
        if not isinstance(payload, dict):
            continue

        if record_type == "event_msg" and payload.get("type") == "user_message":
            content = payload.get("message")
            if isinstance(content, str) and content.strip():
                messages.append(
                    TranscriptMessage(role="user", content=content, timestamp=timestamp)
                )
        elif record_type == "response_item" and payload.get("type") == "message":
            role = payload.get("role")
            if role != "assistant":
                continue
            content = _extract_text_content(payload.get("content"), "output_text")
            if content:
                messages.append(
                    TranscriptMessage(role="assistant", content=content, timestamp=timestamp)
                )
        elif record_type == "response_item" and payload.get("type") in {
            "function_call",
            "function_call_output",
        }:
            tool_events += 1

    if not messages:
        raise SessionConversionError(
            f"Codex session {source_session} did not contain any visible user/assistant messages."
        )

    warnings: list[str] = []
    if tool_events:
        warnings.append(
            f"{tool_events} Codex tool events were present in the source session. "
            "Visible chat history can be migrated, but Codex tool calls and tool outputs are not transferable."
        )

    return messages, warnings


def _gemini_session_ids(path: Path) -> set[str]:
    session_ids: set[str] = set()
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        session_id = record.get("sessionId")
        if isinstance(session_id, str):
            session_ids.add(session_id)
        patch = record.get("$set")
        if isinstance(patch, dict):
            patched_id = patch.get("sessionId")
            if isinstance(patched_id, str):
                session_ids.add(patched_id)
    return session_ids


def _resolve_gemini_session_paths(home_dir: Path, source_session: str) -> list[Path]:
    direct_path = Path(source_session).expanduser()
    if direct_path.exists():
        return [direct_path]

    sessions_root = home_dir / ".gemini" / "tmp"
    matches: list[Path] = []
    for path in sorted(sessions_root.glob("**/chats/session-*.jsonl")):
        if any(session_id.startswith(source_session) for session_id in _gemini_session_ids(path)):
            matches.append(path)

    if not matches:
        raise SessionConversionError(
            f"Could not find Gemini session {source_session} under {sessions_root}."
        )
    return matches


def _extract_gemini_user_content(content: object) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())
    return "\n".join(parts)


def _extract_gemini_transcript(
    home_dir: Path,
    source_session: str,
) -> tuple[list[TranscriptMessage], list[str]]:
    session_paths = _resolve_gemini_session_paths(home_dir, source_session)
    messages: list[TranscriptMessage] = []
    tool_messages = 0

    for path in sorted(session_paths):
        for line in path.read_text().splitlines():
            if not line.strip():
                continue

            record = json.loads(line)
            record_type = record.get("type")
            timestamp = str(record.get("timestamp", ""))

            if record_type == "user":
                content = _extract_gemini_user_content(record.get("content"))
                if content:
                    messages.append(
                        TranscriptMessage(role="user", content=content, timestamp=timestamp)
                    )
            elif record_type == "gemini":
                content = record.get("content")
                if isinstance(content, str) and content.strip():
                    messages.append(
                        TranscriptMessage(role="assistant", content=content, timestamp=timestamp)
                    )
                tokens = record.get("tokens")
                if isinstance(tokens, dict) and int(tokens.get("tool", 0) or 0) > 0:
                    tool_messages += 1

    if not messages:
        raise SessionConversionError(
            f"Gemini session {source_session} did not contain any visible user/assistant messages."
        )

    warnings: list[str] = []
    if tool_messages:
        warnings.append(
            f"{tool_messages} Gemini assistant messages referenced tool usage. "
            "Visible chat history can be migrated, but Gemini tool activity is not transferable."
        )

    return messages, warnings


def _resolve_agy_transcript_path(home_dir: Path, source_session: str) -> Path:
    direct_path = Path(source_session).expanduser()
    if direct_path.exists():
        return direct_path

    brain_root = home_dir / ".gemini" / "antigravity-cli" / "brain" / source_session
    full_transcript = brain_root / ".system_generated" / "logs" / "transcript_full.jsonl"
    transcript = brain_root / ".system_generated" / "logs" / "transcript.jsonl"
    if full_transcript.exists():
        return full_transcript
    if transcript.exists():
        return transcript

    raise SessionConversionError(
        f"Could not find AGY transcript for source session {source_session}. "
        "Pass an AGY brain ID or a full transcript path."
    )


def _extract_agy_user_content(content: object) -> str:
    if not isinstance(content, str):
        return ""
    match = re.search(r"<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>", content, re.DOTALL)
    if not match:
        return ""
    return match.group(1).strip()


def _extract_agy_transcript(
    home_dir: Path,
    source_session: str,
) -> tuple[list[TranscriptMessage], list[str]]:
    transcript_path = _resolve_agy_transcript_path(home_dir, source_session)
    messages: list[TranscriptMessage] = []
    tool_events = 0

    for line in transcript_path.read_text().splitlines():
        if not line.strip():
            continue

        record = json.loads(line)
        timestamp = str(record.get("created_at", ""))
        record_type = record.get("type")
        source = record.get("source")

        if record_type == "USER_INPUT" and source == "USER_EXPLICIT":
            content = _extract_agy_user_content(record.get("content"))
            if content:
                messages.append(
                    TranscriptMessage(role="user", content=content, timestamp=timestamp)
                )
        elif record_type == "PLANNER_RESPONSE" and source == "MODEL":
            tool_calls = record.get("tool_calls")
            if isinstance(tool_calls, list) and tool_calls:
                tool_events += 1
            content = record.get("content")
            if isinstance(content, str) and content.strip():
                messages.append(
                    TranscriptMessage(role="assistant", content=content, timestamp=timestamp)
                )

    if not messages:
        raise SessionConversionError(
            f"AGY session {source_session} did not contain any visible user/assistant messages."
        )

    warnings: list[str] = []
    if tool_events:
        warnings.append(
            f"{tool_events} AGY planner responses referenced tool calls. "
            "Visible chat history can be migrated, but AGY tool activity is not transferable."
        )

    return messages, warnings


def _resolve_claude_session_path(home_dir: Path, source_session: str) -> Path:
    direct_path = Path(source_session).expanduser()
    if direct_path.exists():
        return direct_path

    matches = sorted((home_dir / ".claude" / "projects").glob(f"**/{source_session}.jsonl"))
    if not matches:
        raise SessionConversionError(
            f"Could not find Claude session {source_session} under {home_dir / '.claude' / 'projects'}."
        )
    if len(matches) > 1:
        sample = ", ".join(str(path) for path in matches[:3])
        raise SessionConversionError(
            f"Source session {source_session} matched multiple Claude sessions. "
            f"Pass the full session path instead. Matches include: {sample}"
        )
    return matches[0]


def _extract_claude_assistant_content(content: object) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "text":
            continue
        text = item.get("text")
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())
    return "\n".join(parts)


def _extract_claude_transcript(
    home_dir: Path,
    source_session: str,
) -> tuple[list[TranscriptMessage], list[str]]:
    session_path = _resolve_claude_session_path(home_dir, source_session)
    messages: list[TranscriptMessage] = []
    nonportable_items = 0

    for line in session_path.read_text().splitlines():
        if not line.strip():
            continue

        record = json.loads(line)
        record_type = record.get("type")
        timestamp = str(record.get("timestamp", ""))
        if record_type == "user":
            if record.get("isMeta"):
                continue
            message = record.get("message", {})
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                messages.append(
                    TranscriptMessage(role="user", content=content, timestamp=timestamp)
                )
        elif record_type == "assistant":
            message = record.get("message", {})
            if not isinstance(message, dict):
                continue
            raw_content = message.get("content")
            content = _extract_claude_assistant_content(raw_content)
            if content:
                messages.append(
                    TranscriptMessage(role="assistant", content=content, timestamp=timestamp)
                )
            if isinstance(raw_content, list) and any(
                isinstance(item, dict) and item.get("type") != "text" for item in raw_content
            ):
                nonportable_items += 1
        elif record_type == "attachment":
            nonportable_items += 1

    if not messages:
        raise SessionConversionError(
            f"Claude session {source_session} did not contain any visible user/assistant messages."
        )

    warnings: list[str] = []
    if nonportable_items:
        warnings.append(
            f"{nonportable_items} Claude records included attachments or non-text assistant items. "
            "Only visible text history is portable to other targets."
        )

    return messages, warnings


SOURCE_EXTRACTORS = {
    "claude": _extract_claude_transcript,
    "copilot": _extract_copilot_transcript,
    "codex": _extract_codex_transcript,
    "gemini": _extract_gemini_transcript,
    "agy": _extract_agy_transcript,
}


def _sanitize_project_path(cwd: Path) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", str(cwd.resolve()))


def _claude_project_dir(home_dir: Path, cwd: Path) -> Path:
    return home_dir / ".claude" / "projects" / _sanitize_project_path(cwd)


def _claude_version() -> str:
    try:
        result = subprocess.run(
            ["claude", "--version"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip() or "unknown"


def _git_branch(cwd: Path) -> str | None:
    git_root = wrapper._git_root(cwd)
    if git_root is None:
        return None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            cwd=cwd,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    branch = result.stdout.strip()
    return branch or None


def _assistant_message_payload(content: str) -> dict[str, object]:
    return {
        "id": str(uuid.uuid4()),
        "role": "assistant",
        "type": "message",
        "model": "<synthetic>",
        "content": [{"type": "text", "text": content}],
        "stop_reason": "stop_sequence",
        "stop_sequence": "",
        "stop_details": None,
        "usage": {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
            "server_tool_use": {
                "web_search_requests": 0,
                "web_fetch_requests": 0,
            },
            "service_tier": None,
            "cache_creation": {
                "ephemeral_1h_input_tokens": 0,
                "ephemeral_5m_input_tokens": 0,
            },
            "inference_geo": None,
            "iterations": None,
            "speed": None,
        },
        "container": None,
        "context_management": None,
    }


def _write_claude_session(
    messages: list[TranscriptMessage],
    cwd: Path,
    home_dir: Path,
    target_session: str,
) -> Path:
    project_dir = _claude_project_dir(home_dir, cwd)
    project_dir.mkdir(parents=True, exist_ok=True)
    target_path = project_dir / f"{target_session}.jsonl"
    version = _claude_version()
    git_branch = _git_branch(cwd)
    parent_uuid: str | None = None
    records: list[dict[str, object]] = [
        {"type": "mode", "mode": "normal", "sessionId": target_session},
        {
            "type": "permission-mode",
            "permissionMode": "default",
            "sessionId": target_session,
        },
    ]

    for message in messages:
        record_uuid = str(uuid.uuid4())
        record: dict[str, object] = {
            "parentUuid": parent_uuid,
            "isSidechain": False,
            "type": message.role,
            "uuid": record_uuid,
            "timestamp": message.timestamp,
            "userType": "external",
            "entrypoint": "cli",
            "cwd": str(cwd),
            "sessionId": target_session,
            "version": version,
        }
        if git_branch is not None:
            record["gitBranch"] = git_branch

        if message.role == "user":
            record["promptId"] = str(uuid.uuid4())
            record["message"] = {"role": "user", "content": message.content}
        else:
            record["message"] = _assistant_message_payload(message.content)

        records.append(record)
        parent_uuid = record_uuid

    target_path.write_text("\n".join(json.dumps(record) for record in records) + "\n")
    return target_path


def _write_gemini_session(
    messages: list[TranscriptMessage],
    cwd: Path,
    _home_dir: Path,
    target_session: str,
) -> Path:
    _scope_dir, state_path, _scope_kind = wrapper._state_file("gemini", cwd)
    target_path = state_path.parent / f"gemini-session-{target_session}.jsonl"
    target_path.parent.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, object]] = [
        {
            "kind": "main",
            "sessionId": target_session,
            "projectHash": _sanitize_project_path(cwd),
            "startTime": messages[0].timestamp if messages else "",
            "lastUpdated": messages[-1].timestamp if messages else "",
        }
    ]

    for message in messages:
        if message.role == "user":
            records.append(
                {
                    "type": "user",
                    "id": str(uuid.uuid4()),
                    "timestamp": message.timestamp,
                    "content": [{"text": message.content}],
                }
            )
        else:
            records.append(
                {
                    "type": "gemini",
                    "id": str(uuid.uuid4()),
                    "timestamp": message.timestamp,
                    "content": message.content,
                    "thoughts": [],
                    "tokens": {
                        "cached": 0,
                        "input": 0,
                        "output": 0,
                        "thoughts": 0,
                        "tool": 0,
                        "total": 0,
                    },
                    "model": "synthetic",
                }
            )

    target_path.write_text("\n".join(json.dumps(record) for record in records) + "\n")
    return target_path


TARGET_WRITERS = {
    "claude": _write_claude_session,
    "gemini": _write_gemini_session,
}


def convert_session(
    source_tool: str,
    target_tool: str,
    *,
    cwd: Path | None = None,
    home_dir: Path | None = None,
    source_session: str | None = None,
    target_session: str | None = None,
    apply_state: bool = True,
) -> ConversionResult:
    cwd = (cwd or Path.cwd()).resolve()
    home_dir = (home_dir or Path.home()).resolve()

    if target_tool not in TARGET_WRITERS or source_tool not in SOURCE_EXTRACTORS:
        raise SessionConversionError(
            f"Unsupported conversion: {source_tool} -> {target_tool}. "
            "Currently supported targets: claude and gemini."
        )

    resolved_source_session = _resolve_source_session(source_tool, cwd, source_session)
    messages, warnings = SOURCE_EXTRACTORS[source_tool](home_dir, resolved_source_session)
    resolved_target_session = target_session or str(uuid.uuid4())
    target_path = TARGET_WRITERS[target_tool](messages, cwd, home_dir, resolved_target_session)

    applied_state_path: Path | None = None
    if apply_state:
        _, applied_state_path, _ = wrapper._state_file(target_tool, cwd)
        resume_target = resolved_target_session if target_tool == "claude" else str(target_path)
        wrapper._write_state(
            applied_state_path,
            wrapper._state_payload(
                wrapper.get_tool(target_tool),
                resume_target=resume_target,
            ),
        )

    return ConversionResult(
        source_tool=source_tool,
        target_tool=target_tool,
        source_session=resolved_source_session,
        target_session=resolved_target_session,
        target_path=target_path,
        applied_state_path=applied_state_path,
        message_count=len(messages),
        warnings=tuple(warnings),
    )
