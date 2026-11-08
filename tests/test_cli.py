from __future__ import annotations

import tempfile
import unittest
import os
import subprocess
import sys
from argparse import Namespace
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from ai_session_manager import cli


class VersionTests(unittest.TestCase):
    def test_version_reports_installed_metadata_and_exits_successfully(self) -> None:
        output = StringIO()
        with patch.object(cli, "package_version", return_value="9.8.7") as metadata:
            with patch.object(sys, "argv", ["ai-session-manager", "--version"]):
                with redirect_stdout(output):
                    with self.assertRaises(SystemExit) as result:
                        cli.main()
        self.assertEqual(result.exception.code, 0)
        self.assertEqual(output.getvalue().strip(), "ai-session-manager 9.8.7")
        metadata.assert_called_once_with("ai-session-manager")

    def test_version_handles_source_checkout_without_installed_metadata(self) -> None:
        output = StringIO()
        with patch.object(cli, "package_version", side_effect=cli.PackageNotFoundError):
            with patch.object(sys, "argv", ["ai-session-manager", "--version"]):
                with redirect_stdout(output):
                    with self.assertRaises(SystemExit) as result:
                        cli.main()
        self.assertEqual(result.exception.code, 0)
        self.assertEqual(output.getvalue().strip(),
                         "ai-session-manager unknown (package metadata unavailable)")


class IsolatedCLI(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.shims = self.root / "shims"
        override = patch.dict(os.environ, {"AI_SESSION_MANAGER_BIN_DIR": str(self.shims)})
        override.start()
        self.addCleanup(override.stop)


class TeardownWindowsTests(IsolatedCLI):
    def test_teardown_restores_exe_when_wrapper_is_cmd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            bin_dir = Path(tmp_dir)
            wrapper_path = bin_dir / "copilot.cmd"
            real_path = bin_dir / "copilot-real.exe"
            wrapper_path.write_text("@echo off\npython -c \"from ai_session_manager.wrapper import run; run()\" %*\n")
            real_path.write_bytes(b"MZ")

            def find_binary(name: str) -> Path | None:
                if name == "copilot":
                    return wrapper_path
                if name == "copilot-real":
                    return real_path
                return None

            with patch("ai_session_manager.cli.IS_WINDOWS", True):
                with patch("ai_session_manager.cli._find_binary", side_effect=find_binary):
                    exit_code = cli.cmd_teardown(Namespace(tools=["copilot"]))

            self.assertEqual(exit_code, 0)
            self.assertFalse(wrapper_path.exists())
            self.assertFalse(real_path.exists())
            self.assertTrue((bin_dir / "copilot.exe").exists())


class SetupSymlinkTests(IsolatedCLI):
    @unittest.skipIf(os.name == "nt", "POSIX symlink wrapper")
    def test_setup_preserves_symlink_and_its_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            bin_dir = root / "bin"
            target_dir = root / "target"
            bin_dir.mkdir()
            target_dir.mkdir()
            shim_path = bin_dir / "claude"
            target_path = target_dir / "index.js"
            target_path.write_text("console.log('claude');\n")
            shim_path.symlink_to(target_path)

            with patch("ai_session_manager.cli.find_original", return_value=shim_path):
                exit_code = cli.cmd_setup(Namespace(tools=["claude"]))

            self.assertEqual(exit_code, 0)
            self.assertTrue(shim_path.exists())
            self.assertFalse((bin_dir / "claude-real").exists())
            self.assertTrue(shim_path.is_symlink())
            self.assertEqual(shim_path.resolve(), target_path)
            self.assertEqual(target_path.read_text(), "console.log('claude');\n")
            wrapper_path = self.shims / "claude"
            self.assertTrue(wrapper_path.exists())
            self.assertIn("ai_session_manager.wrapper", wrapper_path.read_text())

    def test_setup_fails_cleanly_when_wrapper_exists_but_real_binary_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            bin_dir = Path(tmp_dir)
            wrapper_path = bin_dir / "claude"
            wrapper_path.write_text(
                "#!/usr/bin/env python3\nfrom ai_session_manager.wrapper import run\nrun('claude')\n"
            )

            with patch("ai_session_manager.cli._find_binary", return_value=wrapper_path):
                exit_code = cli.cmd_setup(Namespace(tools=["claude"]))

            self.assertEqual(exit_code, 1)
            self.assertFalse((bin_dir / "claude-real").exists())


@unittest.skipIf(os.name == "nt", "POSIX executable integration tests")
class SafeInstallationTests(IsolatedCLI):
    def setUp(self) -> None:
        super().setUp()
        self.native_dir = self.root / "native tools"
        self.native_dir.mkdir()
        self.native = self.native_dir / "copilot"
        self.native.write_text("#!/bin/sh\nprintf 'native:%s\\n' \"$@\"\n")
        self.native.chmod(0o755)
        environment = patch.dict(os.environ, {
            "PATH": str(self.shims) + os.pathsep + str(self.native_dir) + os.pathsep + os.environ.get("PATH", ""),
            "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
        })
        environment.start()
        self.addCleanup(environment.stop)

    def test_setup_launch_update_and_teardown_preserve_native_binary(self) -> None:
        before = self.native.read_bytes()
        self.assertEqual(cli.cmd_setup(Namespace(tools=["copilot"])), 0)
        self.assertEqual(cli.cmd_setup(Namespace(tools=["copilot"])), 0)
        shim = self.shims / "copilot"
        result = subprocess.run([str(shim), "--version", "a b", "$(literal)"],
                                capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.splitlines(), ["native:--version", "native:a b", "native:$(literal)"])
        self.assertEqual(self.native.read_bytes(), before)
        self.native.write_text("#!/bin/sh\nexit 17\n")
        result = subprocess.run([str(shim), "--version"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 17)
        self.assertEqual(cli.cmd_teardown(Namespace(tools=["copilot"])), 0)
        self.assertFalse(shim.exists())
        self.assertEqual(self.native.read_text(), "#!/bin/sh\nexit 17\n")

    def test_unrelated_file_and_symlink_are_never_overwritten(self) -> None:
        self.shims.mkdir()
        shim = self.shims / "copilot"
        shim.write_text("personal script")
        self.assertEqual(cli.cmd_setup(Namespace(tools=["copilot"])), 1)
        self.assertEqual(cli.cmd_teardown(Namespace(tools=["copilot"])), 1)
        self.assertEqual(shim.read_text(), "personal script")
        shim.unlink()
        shim.symlink_to(self.native)
        self.assertEqual(cli.cmd_setup(Namespace(tools=["copilot"])), 1)
        self.assertTrue(shim.is_symlink())

    def test_python_interpreter_path_with_spaces(self) -> None:
        interpreter = self.root / "Python with spaces" / "python"
        interpreter.parent.mkdir()
        interpreter.symlink_to(sys.executable)
        with patch.object(cli.sys, "executable", str(interpreter)):
            self.assertEqual(cli.cmd_setup(Namespace(tools=["copilot"])), 0)
        result = subprocess.run([str(self.shims / "copilot"), "--version"],
                                capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.strip(), "native:--version")

    def test_status_explains_shadowed_wrapper_and_does_not_modify_state(self) -> None:
        cli.cmd_setup(Namespace(tools=["copilot"]))
        project = self.root / "project"
        project.mkdir()
        with patch.dict(os.environ, {"PATH": str(self.native_dir) + os.pathsep + str(self.shims)}):
            with patch("ai_session_manager.cli._state_file", return_value=(project, project / "copilot.json", "folder")):
                output = StringIO()
                with redirect_stdout(output):
                    result = cli.cmd_status(Namespace(tools=["copilot"]))
        self.assertEqual(result, 1)
        self.assertIn("shadowed", output.getvalue())
        self.assertEqual(list(project.iterdir()), [])

    def test_legacy_teardown_does_not_overwrite_reinstalled_binary(self) -> None:
        saved = self.native_dir / "copilot-real"
        saved.write_text("old binary")
        saved.chmod(0o755)
        before = self.native.read_bytes()
        self.assertEqual(cli.cmd_teardown(Namespace(tools=["copilot"])), 1)
        self.assertEqual(self.native.read_bytes(), before)
        self.assertEqual(saved.read_text(), "old binary")


@unittest.skipUnless(os.name == "nt", "Windows CMD wrapper integration")
class WindowsInstallationTests(IsolatedCLI):
    def test_cmd_setup_launch_and_teardown_preserve_native_tool(self) -> None:
        native_dir = self.root / "native tools"
        native_dir.mkdir()
        native = native_dir / "copilot.cmd"
        native.write_text("@echo off\r\necho native-tool\r\nexit /b 9\r\n")
        before = native.read_bytes()
        environment = dict(os.environ,
                           PATH=str(self.shims) + os.pathsep + str(native_dir) + os.pathsep + os.environ.get("PATH", ""),
                           PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
        with patch.dict(os.environ, environment):
            self.assertEqual(cli.cmd_setup(Namespace(tools=["copilot"])), 0)
            result = subprocess.run([str(self.shims / "copilot.cmd"), "--version"],
                                    capture_output=True, text=True, cwd=self.root, timeout=10)
            self.assertEqual(result.returncode, 9, result.stderr)
            self.assertIn("native-tool", result.stdout)
            self.assertEqual(cli.cmd_teardown(Namespace(tools=["copilot"])), 0)
        self.assertEqual(native.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
