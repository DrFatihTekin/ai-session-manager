from __future__ import annotations

import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from ai_session_manager import wrapper


class SessionTargetTests(unittest.TestCase):
    def test_git_repo_uses_state_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_dir = Path(tmp_dir)
            subprocess.run(["git", "init", "-q"], cwd=repo_dir, check=True)

            scope_dir, state_file, scope_kind = wrapper._state_file("copilot", repo_dir)

            self.assertEqual(scope_kind, "repo")
            self.assertEqual(scope_dir, repo_dir.resolve())
            self.assertEqual(
                state_file,
                repo_dir.resolve() / f".{wrapper.STATE_DIR_NAME}" / "copilot.json",
            )

    def test_plain_folder_uses_hidden_state_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            folder_dir = Path(tmp_dir)

            scope_dir, state_file, scope_kind = wrapper._state_file("claude", folder_dir)

            self.assertEqual(scope_kind, "folder")
            self.assertEqual(scope_dir, folder_dir.resolve())
            self.assertEqual(
                state_file,
                folder_dir.resolve() / f".{wrapper.STATE_DIR_NAME}" / "claude.json",
            )

    def test_copilot_migrates_legacy_state_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            folder_dir = Path(tmp_dir)
            legacy_path = folder_dir / wrapper.LEGACY_FOLDER_SESSION_FILE
            legacy_path.write_text("legacy-session-id")

            state = wrapper._load_state(wrapper.get_tool("copilot"), folder_dir)

            self.assertEqual(state["resume_target"], "legacy-session-id")
            _, state_path, _ = wrapper._state_file("copilot", folder_dir)
            self.assertTrue(state_path.exists())

    def test_copilot_run_creates_managed_session_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            folder_dir = Path(tmp_dir)
            stdout = StringIO()

            with patch("ai_session_manager.wrapper.Path.cwd", return_value=folder_dir):
                with patch("ai_session_manager.wrapper._find_real_binary", return_value="copilot-real"):
                    with patch("ai_session_manager.wrapper._exec") as exec_mock:
                        with patch("ai_session_manager.wrapper.sys.argv", ["copilot"]):
                            with redirect_stdout(stdout):
                                wrapper.run("copilot")

            _, state_path, _ = wrapper._state_file("copilot", folder_dir)
            session_id = wrapper.json.loads(state_path.read_text())["resume_target"]
            exec_mock.assert_called_once_with("copilot-real", ["--session-id", session_id])
            self.assertIn("[ai-session-manager] New session", stdout.getvalue())

    def test_claude_uses_managed_session_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_dir = Path(tmp_dir)
            folder_dir = root_dir / "project"
            folder_dir.mkdir()
            home_dir = root_dir / "home"
            stdout = StringIO()

            with patch("ai_session_manager.wrapper.Path.cwd", return_value=folder_dir):
                with patch("ai_session_manager.wrapper.Path.home", return_value=home_dir):
                    with patch("ai_session_manager.wrapper._find_real_binary", return_value="claude-real"):
                        with patch("ai_session_manager.wrapper._exec") as exec_mock:
                            with patch("ai_session_manager.wrapper.sys.argv", ["claude"]):
                                with redirect_stdout(stdout):
                                    wrapper.run("claude")

            _, state_path, _ = wrapper._state_file("claude", folder_dir)
            session_id = wrapper.json.loads(state_path.read_text())["resume_target"]
            exec_mock.assert_called_once_with("claude-real", ["--session-id", session_id])
            self.assertIn("[ai-session-manager] New session", stdout.getvalue())
            with patch("ai_session_manager.wrapper.Path.home", return_value=home_dir):
                session_file = wrapper._claude_session_file(session_id, folder_dir)
            session_file.parent.mkdir(parents=True, exist_ok=True)
            session_file.write_text("{}\n")

            with patch("ai_session_manager.wrapper.Path.cwd", return_value=folder_dir):
                with patch("ai_session_manager.wrapper.Path.home", return_value=home_dir):
                    with patch("ai_session_manager.wrapper._find_real_binary", return_value="claude-real"):
                        with patch("ai_session_manager.wrapper._exec") as exec_mock:
                            with patch("ai_session_manager.wrapper.sys.argv", ["claude"]):
                                wrapper.run("claude")

            exec_mock.assert_called_once_with("claude-real", ["-r", session_id])

    def test_agy_discovers_latest_conversation_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            folder_dir = root / "project"
            folder_dir.mkdir()
            home_dir = root / "home"
            history_path = home_dir / ".gemini" / "antigravity-cli" / "history.jsonl"
            history_path.parent.mkdir(parents=True)
            history_path.write_text(
                wrapper.json.dumps(
                    {
                        "display": "hello",
                        "timestamp": 1,
                        "workspace": str(folder_dir.resolve()),
                        "conversationId": "agy-conversation-id",
                    }
                )
                + "\n"
            )
            _, state_path, _ = wrapper._state_file("agy", folder_dir)
            state_path.parent.mkdir(parents=True)
            state_path.write_text(wrapper.json.dumps(wrapper._state_payload(wrapper.get_tool("agy"))) + "\n")

            with patch("ai_session_manager.wrapper.Path.cwd", return_value=folder_dir):
                with patch("ai_session_manager.wrapper.Path.home", return_value=home_dir):
                    with patch("ai_session_manager.wrapper._git_root", return_value=None):
                        with patch("ai_session_manager.wrapper._find_real_binary", return_value="agy-real"):
                            with patch("ai_session_manager.wrapper.subprocess.run") as run_mock:
                                run_mock.return_value.returncode = 0
                                with patch("ai_session_manager.wrapper.sys.argv", ["agy"]):
                                    with self.assertRaises(SystemExit) as exc_info:
                                        wrapper.run("agy")

            self.assertEqual(exc_info.exception.code, 0)
            run_mock.assert_called_once_with(["agy-real", "--conversation", "agy-conversation-id"])
            self.assertEqual(wrapper.json.loads(state_path.read_text())["resume_target"], "agy-conversation-id")

    def test_agy_falls_back_to_matching_latest_brain_when_history_lacks_conversation_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            folder_dir = root / "project"
            folder_dir.mkdir()
            home_dir = root / "home"
            history_path = home_dir / ".gemini" / "antigravity-cli" / "history.jsonl"
            history_path.parent.mkdir(parents=True)
            history_path.write_text(
                wrapper.json.dumps(
                    {
                        "display": "new agy prompt",
                        "timestamp": 2,
                        "workspace": str(folder_dir.resolve()),
                    }
                )
                + "\n"
            )
            brain_dir = home_dir / ".gemini" / "antigravity-cli" / "brain" / "new-brain-id"
            transcript = brain_dir / ".system_generated" / "logs" / "transcript_full.jsonl"
            transcript.parent.mkdir(parents=True, exist_ok=True)
            transcript.write_text(
                wrapper.json.dumps(
                    {
                        "type": "USER_INPUT",
                        "source": "USER_EXPLICIT",
                        "content": "<USER_REQUEST>\nnew agy prompt\n</USER_REQUEST>",
                    }
                )
                + "\n"
            )
            _, state_path, _ = wrapper._state_file("agy", folder_dir)
            state_path.parent.mkdir(parents=True)
            state_path.write_text(wrapper.json.dumps(wrapper._state_payload(wrapper.get_tool("agy"))) + "\n")

            with patch("ai_session_manager.wrapper.Path.cwd", return_value=folder_dir):
                with patch("ai_session_manager.wrapper.Path.home", return_value=home_dir):
                    with patch("ai_session_manager.wrapper._git_root", return_value=None):
                        with patch("ai_session_manager.wrapper._find_real_binary", return_value="agy-real"):
                            with patch("ai_session_manager.wrapper.subprocess.run") as run_mock:
                                run_mock.return_value.returncode = 0
                                with patch("ai_session_manager.wrapper.sys.argv", ["agy"]):
                                    with self.assertRaises(SystemExit):
                                        wrapper.run("agy")

            self.assertEqual(wrapper.json.loads(state_path.read_text())["resume_target"], "new-brain-id")

    def test_agy_prints_resume_id_from_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            folder_dir = root / "project"
            folder_dir.mkdir()
            home_dir = root / "home"
            history_path = home_dir / ".gemini" / "antigravity-cli" / "history.jsonl"
            history_path.parent.mkdir(parents=True)
            history_path.write_text(
                wrapper.json.dumps(
                    {
                        "display": "hello",
                        "timestamp": 1,
                        "workspace": str(folder_dir.resolve()),
                        "conversationId": "agy-conversation-id",
                    }
                )
                + "\n"
            )
            _, state_path, _ = wrapper._state_file("agy", folder_dir)
            state_path.parent.mkdir(parents=True)
            state_path.write_text(
                wrapper.json.dumps(wrapper._state_payload(wrapper.get_tool("agy"), "agy-conversation-id")) + "\n"
            )
            stdout = StringIO()

            with patch("ai_session_manager.wrapper.Path.cwd", return_value=folder_dir):
                with patch("ai_session_manager.wrapper.Path.home", return_value=home_dir):
                    with patch("ai_session_manager.wrapper._git_root", return_value=None):
                        with patch("ai_session_manager.wrapper._find_real_binary", return_value="agy-real"):
                            with patch("ai_session_manager.wrapper.subprocess.run") as run_mock:
                                run_mock.return_value.returncode = 0
                                with patch("ai_session_manager.wrapper.sys.argv", ["agy"]):
                                    with redirect_stdout(stdout):
                                        with self.assertRaises(SystemExit):
                                            wrapper.run("agy")

            self.assertIn("[ai-session-manager] Resuming session agy-conversation-id", stdout.getvalue())
            run_mock.assert_called_once_with(["agy-real", "--conversation", "agy-conversation-id"])

    def test_codex_discovers_latest_session_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            folder_dir = root / "project"
            folder_dir.mkdir()
            home_dir = root / "home"
            session_path = home_dir / ".codex" / "sessions" / "2026" / "06" / "05" / "rollout.jsonl"
            session_path.parent.mkdir(parents=True)
            session_path.write_text(
                "\n".join(
                    [
                        wrapper.json.dumps(
                            {
                                "type": "session_meta",
                                "payload": {
                                    "id": "codex-session-id",
                                    "cwd": str(folder_dir.resolve()),
                                },
                            }
                        )
                    ]
                )
                + "\n"
            )
            history_path = home_dir / ".codex" / "history.jsonl"
            history_path.parent.mkdir(parents=True, exist_ok=True)
            history_path.write_text(
                wrapper.json.dumps({"session_id": "codex-session-id", "ts": 1, "text": "hello"}) + "\n"
            )
            _, state_path, _ = wrapper._state_file("codex", folder_dir)
            state_path.parent.mkdir(parents=True)
            state_path.write_text(wrapper.json.dumps(wrapper._state_payload(wrapper.get_tool("codex"))) + "\n")

            with patch("ai_session_manager.wrapper.Path.cwd", return_value=folder_dir):
                with patch("ai_session_manager.wrapper.Path.home", return_value=home_dir):
                    with patch("ai_session_manager.wrapper._git_root", return_value=None):
                        with patch("ai_session_manager.wrapper._find_real_binary", return_value="codex-real"):
                            with patch("ai_session_manager.wrapper.subprocess.run") as run_mock:
                                run_mock.return_value.returncode = 0
                                with patch("ai_session_manager.wrapper.sys.argv", ["codex"]):
                                    with self.assertRaises(SystemExit) as exc_info:
                                        wrapper.run("codex")

            self.assertEqual(exc_info.exception.code, 0)
            run_mock.assert_called_once_with(["codex-real", "resume", "codex-session-id"])
            self.assertEqual(wrapper.json.loads(state_path.read_text())["resume_target"], "codex-session-id")

    def test_codex_first_run_records_resume_target_after_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            folder_dir = root / "project"
            folder_dir.mkdir()
            home_dir = root / "home"
            session_path = home_dir / ".codex" / "sessions" / "2026" / "06" / "05" / "rollout.jsonl"
            session_path.parent.mkdir(parents=True)
            session_path.write_text(
                wrapper.json.dumps(
                    {
                        "type": "session_meta",
                        "payload": {
                            "id": "codex-session-id",
                            "cwd": str(folder_dir.resolve()),
                        },
                    }
                )
                + "\n"
            )
            history_path = home_dir / ".codex" / "history.jsonl"
            history_path.parent.mkdir(parents=True, exist_ok=True)
            history_path.write_text(
                wrapper.json.dumps({"session_id": "codex-session-id", "ts": 1, "text": "hello"}) + "\n"
            )

            with patch("ai_session_manager.wrapper.Path.cwd", return_value=folder_dir):
                with patch("ai_session_manager.wrapper.Path.home", return_value=home_dir):
                    with patch("ai_session_manager.wrapper._git_root", return_value=None):
                        with patch("ai_session_manager.wrapper._find_real_binary", return_value="codex-real"):
                            with patch("ai_session_manager.wrapper.subprocess.run") as run_mock:
                                run_mock.return_value.returncode = 0
                                with patch("ai_session_manager.wrapper.sys.argv", ["codex"]):
                                    with self.assertRaises(SystemExit) as exc_info:
                                        wrapper.run("codex")

            self.assertEqual(exc_info.exception.code, 0)
            run_mock.assert_called_once_with(["codex-real"])
            _, state_path, _ = wrapper._state_file("codex", folder_dir)
            self.assertEqual(wrapper.json.loads(state_path.read_text())["resume_target"], "codex-session-id")

    def test_codex_bypasses_explicit_subcommands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            folder_dir = Path(tmp_dir)

            with patch("ai_session_manager.wrapper.Path.cwd", return_value=folder_dir):
                with patch("ai_session_manager.wrapper._find_real_binary", return_value="codex-real"):
                    with patch("ai_session_manager.wrapper._exec") as exec_mock:
                        with patch("ai_session_manager.wrapper.sys.argv", ["codex", "review"]):
                            wrapper.run("codex")

            exec_mock.assert_called_once_with("codex-real", ["review"])
            _, state_path, _ = wrapper._state_file("codex", folder_dir)
            self.assertFalse(state_path.exists())

    def test_stale_real_bin_env_falls_back_to_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            folder_dir = Path(tmp_dir)
            stale_real = folder_dir / "copilot-real.cmd"

            with patch.dict(
                "ai_session_manager.wrapper.os.environ",
                {wrapper.REAL_BIN_ENV: str(stale_real)},
                clear=False,
            ):
                with patch("ai_session_manager.wrapper.Path.cwd", return_value=folder_dir):
                    with patch("ai_session_manager.wrapper._find_real_binary", return_value="copilot-real.exe"):
                        with patch("ai_session_manager.wrapper._should_bypass", return_value=True):
                            with patch("ai_session_manager.wrapper._exec") as exec_mock:
                                with patch("ai_session_manager.wrapper.sys.argv", ["copilot", "--version"]):
                                    wrapper.run("copilot")

            exec_mock.assert_called_once_with("copilot-real.exe", ["--version"])

if __name__ == "__main__":
    unittest.main()
