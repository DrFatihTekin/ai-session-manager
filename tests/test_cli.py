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


if __name__ == "__main__":
    unittest.main()
