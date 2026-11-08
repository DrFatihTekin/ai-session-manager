from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from ai_session_manager import cli, wrapper


class ReliabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.spec = wrapper.get_tool("copilot")
        self.state = self.project / ".ai-session-manager" / "copilot.json"
        cwd = patch("ai_session_manager.wrapper.Path.cwd", return_value=self.project)
        cwd.start()
        self.addCleanup(cwd.stop)
        home = patch("ai_session_manager.wrapper.Path.home", return_value=self.root / "home")
        home.start()
        self.addCleanup(home.stop)

    def test_invalid_state_is_preserved_and_launch_has_recovery_message(self) -> None:
        self.state.parent.mkdir()
        for contents in ("{truncated", "[]", "null", '{"version":99}',
                         json.dumps(wrapper._state_payload(self.spec)),
                         json.dumps(wrapper._state_payload(self.spec, "../other"))):
            with self.subTest(contents=contents):
                self.state.write_text(contents)
                with patch.object(wrapper, "_find_real_binary", return_value="native"):
                    with patch.object(wrapper.sys, "argv", ["copilot"]):
                        with patch.object(wrapper, "_invoke_tool") as launch:
                            with patch("sys.stderr") as stderr:
                                with self.assertRaises(SystemExit) as result:
                                    wrapper.run("copilot")
                self.assertEqual(result.exception.code, 1)
                self.assertEqual(self.state.read_text(), contents)
                launch.assert_not_called()
                self.assertIn("reset copilot", " ".join(str(c) for c in stderr.write.call_args_list))

    def test_failed_atomic_replace_keeps_old_state_and_cleans_temporary_file(self) -> None:
        old = wrapper._state_payload(self.spec, "original")
        wrapper._write_state(self.state, old)
        with patch.object(wrapper.os, "replace", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                wrapper._write_state(self.state, wrapper._state_payload(self.spec, "replacement"))
        self.assertEqual(json.loads(self.state.read_text()), old)
        self.assertEqual(list(self.state.parent.iterdir()), [self.state])

    def test_second_process_cannot_manage_same_project_and_lock_releases(self) -> None:
        source = str(Path(__file__).resolve().parents[1] / "src")
        code = (
            "from pathlib import Path\n"
            "from ai_session_manager.wrapper import _session_lock, get_tool\n"
            f"with _session_lock(get_tool('copilot'), Path({str(self.project)!r})):\n"
            "    print('acquired')\n"
        )
        environment = dict(os.environ, PYTHONPATH=source)
        with wrapper._session_lock(self.spec, self.project):
            blocked = subprocess.run([sys.executable, "-c", code], env=environment,
                                     capture_output=True, text=True, timeout=10)
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("Another managed copilot session", blocked.stderr)
        released = subprocess.run([sys.executable, "-c", code], env=environment,
                                  capture_output=True, text=True, timeout=10)
        self.assertEqual(released.returncode, 0, released.stderr)
        self.assertEqual(released.stdout.strip(), "acquired")

    def test_lock_releases_after_exception_and_different_tools_can_run(self) -> None:
        with self.assertRaises(RuntimeError):
            with wrapper._session_lock(self.spec):
                with wrapper._session_lock(wrapper.get_tool("codex")):
                    raise RuntimeError("child failed")
        with wrapper._session_lock(self.spec):
            pass

    def test_reset_refuses_active_session_and_preserves_state(self) -> None:
        wrapper._write_state(self.state, wrapper._state_payload(self.spec, "original"))
        with wrapper._session_lock(self.spec):
            with self.assertRaisesRegex(ValueError, "Another managed"):
                cli.cmd_reset(Namespace(tools=["copilot"]))
        self.assertEqual(json.loads(self.state.read_text())["resume_target"], "original")
        cli.cmd_reset(Namespace(tools=["copilot"]))
        self.assertFalse(self.state.exists())

    def test_explicit_session_command_bypasses_state_and_lock(self) -> None:
        with wrapper._session_lock(self.spec):
            with patch.object(wrapper, "_find_real_binary", return_value="native"):
                with patch.object(wrapper.sys, "argv", ["copilot", "--resume"]):
                    with patch.object(wrapper, "_exec") as launch:
                        wrapper.run("copilot")
        launch.assert_called_once_with("native", ["--resume"])
        self.assertFalse(self.state.exists())

    def test_missing_exact_session_starts_fresh_instead_of_resuming_latest(self) -> None:
        for key in ("codex", "agy"):
            with self.subTest(tool=key):
                spec = wrapper.get_tool(key)
                _, state_path, _ = wrapper._state_file(key)
                wrapper._write_state(state_path, wrapper._state_payload(spec, "deleted-session"))
                with patch.object(wrapper, "_invoke_tool") as launch:
                    wrapper._run_session(spec, "native", ["hello"], self.project)
                self.assertEqual(launch.call_args.args[2], ["hello"])
                self.assertNotIn("resume_target", json.loads(state_path.read_text()))

    def test_missing_claude_session_uses_managed_id_instead_of_latest(self) -> None:
        spec = wrapper.get_tool("claude")
        args = wrapper._resume_invocation(spec, wrapper._state_payload(spec, "managed-id"), [], self.project)
        self.assertEqual(args, ["--session-id", "managed-id"])

    def test_codex_discovery_skips_broken_records_and_other_projects_without_global_history(self) -> None:
        sessions = self.root / "home" / ".codex" / "sessions"
        sessions.mkdir(parents=True)
        for name, project in (("mine", self.project), ("other", self.root / "other")):
            (sessions / f"{name}.jsonl").write_text(
                'null\n[]\n{truncated\n' + json.dumps({
                    "type": "session_meta", "payload": {"id": name, "cwd": str(project.resolve())}
                }) + "\n"
            )
        self.assertEqual(wrapper._codex_latest_session_id(self.project), "mine")
        self.assertTrue(wrapper._resume_target_is_valid(wrapper.get_tool("codex"), "mine", self.project))
        self.assertFalse(wrapper._resume_target_is_valid(wrapper.get_tool("codex"), "other", self.project))

    def test_managed_child_exit_code_is_preserved(self) -> None:
        for exit_code in (0, 7):
            with patch.object(wrapper.subprocess, "run", return_value=subprocess.CompletedProcess([], exit_code)):
                with self.assertRaises(SystemExit) as result:
                    wrapper._invoke_tool(self.spec, "native", [], self.project)
            self.assertEqual(result.exception.code, exit_code)

    def test_repository_subdirectory_sessions_match_but_nested_repositories_do_not(self) -> None:
        subprocess.run(["git", "init", "-q", str(self.project)], check=True)
        subdirectory = self.project / "src"
        subdirectory.mkdir()
        nested = self.project / "vendor"
        nested.mkdir()
        subprocess.run(["git", "init", "-q", str(nested)], check=True)
        self.assertTrue(wrapper._matches_project(str(subdirectory), self.project))
        self.assertFalse(wrapper._matches_project(str(nested), self.project))
        self.assertFalse(wrapper._matches_project(str(self.root / "other"), self.project))


if __name__ == "__main__":
    unittest.main()
