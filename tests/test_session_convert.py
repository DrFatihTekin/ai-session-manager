from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_session_manager import session_convert, wrapper


def _read_records(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


class SessionConvertTests(unittest.TestCase):
    def test_convert_copilot_to_claude_creates_target_session_and_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            project_dir = root / "project"
            project_dir.mkdir()
            home_dir = root / "home"
            events_dir = home_dir / ".copilot" / "session-state" / "copilot-session"
            events_dir.mkdir(parents=True)
            events_path = events_dir / "events.jsonl"
            events = [
                {
                    "type": "user.message",
                    "timestamp": "2026-06-04T10:00:00Z",
                    "data": {"content": "First prompt"},
                },
                {
                    "type": "assistant.message",
                    "timestamp": "2026-06-04T10:00:01Z",
                    "data": {"content": "First answer", "toolRequests": [{"id": "1"}]},
                },
                {
                    "type": "user.message",
                    "timestamp": "2026-06-04T10:00:02Z",
                    "data": {
                        "content": "Second prompt",
                        "transformedContent": "<current_datetime>stale</current_datetime>",
                    },
                },
            ]
            events_path.write_text("\n".join(json.dumps(event) for event in events) + "\n")

            with patch("ai_session_manager.session_convert._claude_version", return_value="2.1.152"):
                result = session_convert.convert_session(
                    "copilot",
                    "claude",
                    cwd=project_dir,
                    home_dir=home_dir,
                    source_session="copilot-session",
                    target_session="claude-session",
                )

            self.assertEqual(result.source_session, "copilot-session")
            self.assertEqual(result.target_session, "claude-session")
            self.assertEqual(result.message_count, 3)
            self.assertTrue(result.target_path.exists())
            self.assertEqual(len(result.warnings), 1)

            records = _read_records(result.target_path)
            self.assertEqual(records[0]["type"], "mode")
            self.assertEqual(records[1]["type"], "permission-mode")
            self.assertEqual(records[2]["message"]["content"], "First prompt")
            self.assertEqual(
                records[3]["message"]["content"],
                [{"type": "text", "text": "First answer"}],
            )
            self.assertEqual(records[4]["message"]["content"], "Second prompt")

            _, state_path, _ = wrapper._state_file("claude", project_dir)
            self.assertEqual(json.loads(state_path.read_text())["resume_target"], "claude-session")

    def test_convert_codex_to_claude_uses_event_messages_for_user_turns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            project_dir = root / "project"
            project_dir.mkdir()
            home_dir = root / "home"
            session_dir = home_dir / ".codex" / "sessions" / "2026" / "06" / "04"
            session_dir.mkdir(parents=True)
            session_path = session_dir / "rollout-test.jsonl"
            records = [
                {
                    "type": "session_meta",
                    "timestamp": "2026-06-04T10:00:00Z",
                    "payload": {"id": "codex-session-id"},
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-06-04T10:00:00Z",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": "<environment_context>ignore</environment_context>"}],
                    },
                },
                {
                    "type": "event_msg",
                    "timestamp": "2026-06-04T10:00:01Z",
                    "payload": {"type": "user_message", "message": "Real user prompt"},
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-06-04T10:00:02Z",
                    "payload": {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "Assistant reply"}],
                    },
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-06-04T10:00:03Z",
                    "payload": {"type": "function_call"},
                },
            ]
            session_path.write_text("\n".join(json.dumps(record) for record in records) + "\n")

            with patch("ai_session_manager.session_convert._claude_version", return_value="2.1.152"):
                result = session_convert.convert_session(
                    "codex",
                    "claude",
                    cwd=project_dir,
                    home_dir=home_dir,
                    source_session="codex-session-id",
                    target_session="claude-session",
                )

            self.assertEqual(result.message_count, 2)
            self.assertEqual(len(result.warnings), 1)
            migrated = _read_records(result.target_path)
            self.assertEqual(migrated[2]["message"]["content"], "Real user prompt")
            self.assertEqual(
                migrated[3]["message"]["content"],
                [{"type": "text", "text": "Assistant reply"}],
            )

    def test_convert_gemini_to_claude_reads_rotated_session_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            project_dir = root / "project"
            project_dir.mkdir()
            home_dir = root / "home"
            chats_dir = home_dir / ".gemini" / "tmp" / "my-project" / "chats"
            chats_dir.mkdir(parents=True)
            first = chats_dir / "session-2026-06-04T10-00-abcd1234.jsonl"
            second = chats_dir / "session-2026-06-04T10-05-abcd1234.jsonl"
            first.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "kind": "main",
                                "sessionId": "abcd1234-0000-0000-0000-000000000000",
                                "startTime": "2026-06-04T10:00:00Z",
                                "lastUpdated": "2026-06-04T10:00:00Z",
                                "projectHash": "p1",
                            }
                        ),
                        json.dumps(
                            {
                                "type": "user",
                                "timestamp": "2026-06-04T10:00:01Z",
                                "content": [{"text": "Hello Gemini"}],
                            }
                        ),
                    ]
                )
                + "\n"
            )
            second.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "kind": "main",
                                "sessionId": "abcd1234-0000-0000-0000-000000000000",
                                "startTime": "2026-06-04T10:05:00Z",
                                "lastUpdated": "2026-06-04T10:05:00Z",
                                "projectHash": "p1",
                            }
                        ),
                        json.dumps(
                            {
                                "type": "gemini",
                                "timestamp": "2026-06-04T10:05:01Z",
                                "content": "Hello from Gemini",
                                "tokens": {"tool": 1},
                            }
                        ),
                    ]
                )
                + "\n"
            )

            with patch("ai_session_manager.session_convert._claude_version", return_value="2.1.152"):
                result = session_convert.convert_session(
                    "gemini",
                    "claude",
                    cwd=project_dir,
                    home_dir=home_dir,
                    source_session="abcd1234",
                    target_session="claude-session",
                )

            self.assertEqual(result.message_count, 2)
            self.assertEqual(len(result.warnings), 1)
            migrated = _read_records(result.target_path)
            self.assertEqual(migrated[2]["message"]["content"], "Hello Gemini")
            self.assertEqual(
                migrated[3]["message"]["content"],
                [{"type": "text", "text": "Hello from Gemini"}],
            )

    def test_convert_agy_to_claude_extracts_user_request_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            project_dir = root / "project"
            project_dir.mkdir()
            home_dir = root / "home"
            logs_dir = (
                home_dir
                / ".gemini"
                / "antigravity-cli"
                / "brain"
                / "brain-id"
                / ".system_generated"
                / "logs"
            )
            logs_dir.mkdir(parents=True)
            transcript = logs_dir / "transcript_full.jsonl"
            entries = [
                {
                    "type": "USER_INPUT",
                    "source": "USER_EXPLICIT",
                    "status": "DONE",
                    "created_at": "2026-06-04T10:00:00Z",
                    "content": "<USER_REQUEST>\nHelp me please\n</USER_REQUEST>\n<ADDITIONAL_METADATA>\nIgnore\n</ADDITIONAL_METADATA>",
                },
                {
                    "type": "PLANNER_RESPONSE",
                    "source": "MODEL",
                    "status": "DONE",
                    "created_at": "2026-06-04T10:00:01Z",
                    "tool_calls": [{"id": "1"}],
                },
                {
                    "type": "PLANNER_RESPONSE",
                    "source": "MODEL",
                    "status": "DONE",
                    "created_at": "2026-06-04T10:00:02Z",
                    "content": "Sure, here is a helpful answer.",
                },
            ]
            transcript.write_text("\n".join(json.dumps(entry) for entry in entries) + "\n")

            with patch("ai_session_manager.session_convert._claude_version", return_value="2.1.152"):
                result = session_convert.convert_session(
                    "agy",
                    "claude",
                    cwd=project_dir,
                    home_dir=home_dir,
                    source_session="brain-id",
                    target_session="claude-session",
                )

            self.assertEqual(result.message_count, 2)
            self.assertEqual(len(result.warnings), 1)
            migrated = _read_records(result.target_path)
            self.assertEqual(migrated[2]["message"]["content"], "Help me please")
            self.assertEqual(
                migrated[3]["message"]["content"],
                [{"type": "text", "text": "Sure, here is a helpful answer."}],
            )

    def test_non_copilot_sources_require_explicit_source_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_dir = Path(tmp_dir)

            with self.assertRaises(session_convert.SessionConversionError):
                session_convert.convert_session(
                    "gemini",
                    "claude",
                    cwd=project_dir,
                    home_dir=project_dir,
                )

    def test_convert_claude_to_gemini_writes_gemini_session_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            project_dir = root / "project"
            project_dir.mkdir()
            home_dir = root / "home"
            claude_dir = home_dir / ".claude" / "projects" / "sample"
            claude_dir.mkdir(parents=True)
            claude_session = claude_dir / "claude-src.jsonl"
            records = [
                {"type": "mode", "mode": "normal", "sessionId": "claude-src"},
                {"type": "permission-mode", "permissionMode": "default", "sessionId": "claude-src"},
                {
                    "type": "user",
                    "timestamp": "2026-06-04T10:00:00Z",
                    "isSidechain": False,
                    "message": {"role": "user", "content": "Hello from Claude"},
                    "uuid": "u1",
                    "sessionId": "claude-src",
                    "version": "2.1.152",
                },
                {
                    "type": "assistant",
                    "timestamp": "2026-06-04T10:00:01Z",
                    "isSidechain": False,
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "Hello from Claude assistant"}],
                    },
                    "uuid": "a1",
                    "sessionId": "claude-src",
                    "version": "2.1.152",
                },
            ]
            claude_session.write_text("\n".join(json.dumps(record) for record in records) + "\n")

            result = session_convert.convert_session(
                "claude",
                "gemini",
                cwd=project_dir,
                home_dir=home_dir,
                source_session="claude-src",
                target_session="gemini-target",
            )

            self.assertEqual(result.message_count, 2)
            self.assertTrue(result.target_path.exists())
            gemini_records = _read_records(result.target_path)
            self.assertEqual(gemini_records[0]["sessionId"], "gemini-target")
            self.assertEqual(gemini_records[1]["content"], [{"text": "Hello from Claude"}])
            self.assertEqual(gemini_records[2]["content"], "Hello from Claude assistant")

            _, state_path, _ = wrapper._state_file("gemini", project_dir)
            self.assertEqual(json.loads(state_path.read_text())["resume_target"], str(result.target_path))

    def test_convert_rejects_unsupported_pair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_dir = Path(tmp_dir)

            with self.assertRaises(session_convert.SessionConversionError):
                session_convert.convert_session(
                    "claude",
                    "copilot",
                    cwd=project_dir,
                    home_dir=project_dir,
                    source_session="session-id",
                )


class ClaudeResumeTargetTests(unittest.TestCase):
    def test_claude_resume_target_uses_explicit_session_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            project_dir = root / "project"
            project_dir.mkdir()
            home_dir = root / "home"
            session_path = (
                home_dir
                / ".claude"
                / "projects"
                / str(project_dir.resolve()).replace("/", "-")
                / "claude-session.jsonl"
            )
            session_path.parent.mkdir(parents=True)
            session_path.write_text("{}\n")

            with patch("ai_session_manager.wrapper.Path.home", return_value=home_dir):
                invocation = wrapper._resume_invocation(
                    wrapper.get_tool("claude"),
                    {"resume_target": "claude-session"},
                    [],
                    project_dir,
                )

            self.assertEqual(invocation, ["-r", "claude-session"])

    def test_missing_claude_resume_target_falls_back_to_latest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            project_dir = root / "project"
            project_dir.mkdir()
            home_dir = root / "home"

            with patch("ai_session_manager.wrapper.Path.home", return_value=home_dir):
                invocation = wrapper._resume_invocation(
                    wrapper.get_tool("claude"),
                    {"resume_target": "missing-session"},
                    [],
                    project_dir,
                )

            self.assertEqual(invocation, ["-c"])

    def test_gemini_resume_target_uses_session_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            project_dir = root / "project"
            project_dir.mkdir()
            session_file = root / "gemini-session.jsonl"
            session_file.write_text("{}\n")

            invocation = wrapper._resume_invocation(
                wrapper.get_tool("gemini"),
                {"resume_target": str(session_file)},
                [],
                project_dir,
            )

            self.assertEqual(invocation, ["--session-file", str(session_file)])


if __name__ == "__main__":
    unittest.main()
