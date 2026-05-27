from __future__ import annotations

import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from copilot_session import wrapper


class SessionTargetTests(unittest.TestCase):
    def test_git_repo_uses_git_directory_session_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_dir = Path(tmp_dir)
            subprocess.run(["git", "init", "-q"], cwd=repo_dir, check=True)

            scope_dir, session_file, scope_kind = wrapper._session_target(repo_dir)

            self.assertEqual(scope_kind, "repo")
            self.assertEqual(scope_dir, repo_dir.resolve())
            self.assertEqual(session_file, repo_dir.resolve() / ".git" / wrapper.REPO_SESSION_FILE)

    def test_plain_folder_uses_hidden_session_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            folder_dir = Path(tmp_dir)

            scope_dir, session_file, scope_kind = wrapper._session_target(folder_dir)

            self.assertEqual(scope_kind, "folder")
            self.assertEqual(scope_dir, folder_dir.resolve())
            self.assertEqual(session_file, folder_dir.resolve() / wrapper.FOLDER_SESSION_FILE)

    def test_run_creates_folder_session_outside_git(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            folder_dir = Path(tmp_dir)
            stdout = StringIO()

            with patch("copilot_session.wrapper.Path.cwd", return_value=folder_dir):
                with patch("copilot_session.wrapper._find_real_copilot", return_value="copilot-real"):
                    with patch("copilot_session.wrapper._exec") as exec_mock:
                        with patch("copilot_session.wrapper.sys.argv", ["copilot"]):
                            with redirect_stdout(stdout):
                                wrapper.run()

            session_id = (folder_dir / wrapper.FOLDER_SESSION_FILE).read_text().strip()
            self.assertTrue(session_id)
            exec_mock.assert_called_once_with("copilot-real", ["--session-id", session_id])
            self.assertIn("[copilot-session] New session", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
