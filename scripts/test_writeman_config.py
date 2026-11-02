import json
import importlib.util
import tempfile
import unittest
from pathlib import Path

from writeman_config import load_config

CHECKER_PATH = Path(__file__).with_name("check-publication.py")
CHECKER_SPEC = importlib.util.spec_from_file_location("check_publication", CHECKER_PATH)
CHECKER = importlib.util.module_from_spec(CHECKER_SPEC)
CHECKER_SPEC.loader.exec_module(CHECKER)


class WritemanConfigTests(unittest.TestCase):
    def test_loads_private_settings_from_explicit_path(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "local.json"
            path.write_text(json.dumps({"feishu_targets": [{"name": "source", "token": "local-id"}]}))
            self.assertEqual(load_config(path)["feishu_targets"][0]["token"], "local-id")

    def test_missing_configuration_points_to_local_example(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "missing.json"
            with self.assertRaisesRegex(FileNotFoundError, "config/writeman.example.json"):
                load_config(path)

    def test_rejects_non_object_configuration(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "local.json"
            path.write_text("[]")
            with self.assertRaisesRegex(ValueError, "JSON object"):
                load_config(path)

    def test_publication_check_rejects_private_local_configuration(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            config = root / "config"
            config.mkdir()
            (config / "writeman.local.json").write_text('{"token":"synthetic"}')
            errors = CHECKER.publication_errors(root)
            self.assertTrue(any("writeman.local.json" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
