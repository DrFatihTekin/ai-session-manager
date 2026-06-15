from __future__ import annotations

import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from ai_session_manager import cli


class TeardownWindowsTests(unittest.TestCase):
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


class SetupSymlinkTests(unittest.TestCase):
    def test_setup_renames_symlink_path_not_resolved_target(self) -> None:
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

            with patch("ai_session_manager.cli._find_binary", return_value=shim_path):
                exit_code = cli.cmd_setup(Namespace(tools=["claude"]))

            self.assertEqual(exit_code, 0)
            self.assertTrue(shim_path.exists())
            self.assertTrue((bin_dir / "claude-real").is_symlink())
            self.assertEqual((bin_dir / "claude-real").resolve(), target_path)
            wrapper_path = bin_dir / "claude"
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


if __name__ == "__main__":
    unittest.main()
