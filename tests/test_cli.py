from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from feed_forge.cli import main


class CliTests(unittest.TestCase):
    def test_discovery_configuration_failure_writes_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            json_path = Path(directory) / "failure.json"
            markdown_path = Path(directory) / "failure.md"
            with patch.dict(os.environ, {}, clear=True):
                exit_code = main(
                    [
                        "discover-accounts",
                        "--json-output",
                        str(json_path),
                        "--markdown-output",
                        str(markdown_path),
                    ]
                )

            report = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(2, exit_code)
            self.assertEqual("failed", report["status"])
            self.assertEqual("configuration", report["error"]["category"])
            self.assertIn("No X credential", report["error"]["detail"])
            self.assertIn("Status: `failed`", markdown_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
