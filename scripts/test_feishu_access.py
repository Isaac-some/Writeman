import contextlib
import io
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "check_feishu_access", Path(__file__).with_name("check-feishu-access.py")
)
check_feishu_access = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = check_feishu_access
SPEC.loader.exec_module(check_feishu_access)


class FeishuAccessTests(unittest.TestCase):
    def test_permission_report_never_echoes_configured_ids(self):
        with tempfile.TemporaryDirectory() as name:
            config = Path(name) / "local.json"
            config.write_text(json.dumps({
                "feishu_targets": [{
                    "name": "task-source",
                    "type": "wiki",
                    "token": "private-resource-id",
                }],
            }))
            output = io.StringIO()
            result = contextlib.redirect_stdout(output)
            with patch.object(sys, "argv", ["check-feishu-access.py", "--config", str(config)]), \
                 patch.object(check_feishu_access.subprocess, "run", return_value=type(
                     "Result", (), {
                         "returncode": 0,
                         "stdout": json.dumps({
                             "ok": True, "identity": "user", "data": {"auth_result": True},
                         }),
                         "stderr": "",
                     },
                 )()), result:
                self.assertEqual(check_feishu_access.main(), 0)
            self.assertNotIn("private-resource-id", output.getvalue())
            self.assertIn('"granted": true', output.getvalue())

    def test_unconfigured_targets_are_not_treated_as_success(self):
        with tempfile.TemporaryDirectory() as name:
            config = Path(name) / "local.json"
            config.write_text(json.dumps({"feishu_targets": [{"name": "task-source", "type": "wiki"}]}))
            output = io.StringIO()
            with patch.object(sys, "argv", ["check-feishu-access.py", "--config", str(config)]), \
                 contextlib.redirect_stdout(output):
                self.assertEqual(check_feishu_access.main(), 1)
            self.assertIn('"configured": false', output.getvalue())


if __name__ == "__main__":
    unittest.main()
