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
                repo_dir.resolve() / ".git" / wrapper.STATE_DIR_NAME / "copilot.json",
            )

    def test_plain_folder_uses_hidden_state_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            folder_dir = Path(tmp_dir)

            scope_dir, state_file, scope_kind = wrapper._state_file("gemini", folder_dir)

            self.assertEqual(scope_kind, "folder")
            self.assertEqual(scope_dir, folder_dir.resolve())
            self.assertEqual(
                state_file,
                folder_dir.resolve() / f".{wrapper.STATE_DIR_NAME}" / "gemini.json",
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

    def test_gemini_resumes_after_first_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            folder_dir = Path(tmp_dir)

            with patch("ai_session_manager.wrapper.Path.cwd", return_value=folder_dir):
                with patch("ai_session_manager.wrapper._find_real_binary", return_value="gemini-real"):
                    with patch("ai_session_manager.wrapper._exec") as exec_mock:
                        with patch("ai_session_manager.wrapper.sys.argv", ["gemini"]):
                            wrapper.run("gemini")

            exec_mock.assert_called_once_with("gemini-real", [])

            with patch("ai_session_manager.wrapper.Path.cwd", return_value=folder_dir):
                with patch("ai_session_manager.wrapper._find_real_binary", return_value="gemini-real"):
                    with patch("ai_session_manager.wrapper._exec") as exec_mock:
                        with patch("ai_session_manager.wrapper.sys.argv", ["gemini"]):
                            wrapper.run("gemini")

            exec_mock.assert_called_once_with("gemini-real", ["--resume"])

    def test_agy_resumes_after_first_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            folder_dir = Path(tmp_dir)

            with patch("ai_session_manager.wrapper.Path.cwd", return_value=folder_dir):
                with patch("ai_session_manager.wrapper._find_real_binary", return_value="agy-real"):
                    with patch("ai_session_manager.wrapper._exec") as exec_mock:
                        with patch("ai_session_manager.wrapper.sys.argv", ["agy"]):
                            wrapper.run("agy")

            exec_mock.assert_called_once_with("agy-real", [])

            with patch("ai_session_manager.wrapper.Path.cwd", return_value=folder_dir):
                with patch("ai_session_manager.wrapper._find_real_binary", return_value="agy-real"):
                    with patch("ai_session_manager.wrapper._exec") as exec_mock:
                        with patch("ai_session_manager.wrapper.sys.argv", ["agy"]):
                            wrapper.run("agy")

            exec_mock.assert_called_once_with("agy-real", ["-c"])

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

if __name__ == "__main__":
    unittest.main()
