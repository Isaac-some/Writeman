"""Exercise deletion boundaries with disposable files; never call Feishu or Blurt."""
import argparse
import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("media_lifecycle", Path(__file__).with_name("media-lifecycle.py"))
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class MediaLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="writeman-lifecycle-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.recordings = self.root / "recordings"
        self.runs = self.root / "runs"
        self.ledger = self.root / "state/media-receipts.json"
        self.ledger.parent.mkdir()
        self.recording = self.recordings / "20261105-090000"
        self.recording.mkdir(parents=True)
        (self.recording / "recording.mp4").write_bytes(b"original video")
        (self.recording / "events.jsonl").write_text("pointer events")
        self.artifacts = self.runs / "demo-1"
        self.artifacts.mkdir(parents=True)
        self.output = self.artifacts / "final.mp4"
        self.output.write_bytes(b"finished demo")
        self.unrelated = self.recordings / "20261105-080000"
        self.unrelated.mkdir()
        (self.unrelated / "recording.mp4").write_bytes(b"other recording")
        self.args = argparse.Namespace(recording=self.recording, artifacts=self.artifacts, output=self.output,
                                       document_id="newDoc", block_id="attachmentBlock", file_token="videoToken")
        self.data = {"version": 1, "receipts": []}
        self.clock = datetime(2026, 11, 5, 12, 0, tzinfo=MODULE.TZ)
        for name, value in [("RECORDINGS", self.recordings), ("RUNS", self.runs), ("LEDGER", self.ledger),
                            ("REFERENCE_DOC", "reference-document")]:
            p = patch.object(MODULE, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.not_sent = patch.object(MODULE, "ensure_not_sent").start()
        self.remote = patch.object(MODULE, "verify_remote", return_value={"attachmentMatched": True}).start()
        patch.object(MODULE, "local_now", side_effect=lambda: self.clock).start()
        self.addCleanup(patch.stopall)

    def register(self):
        return MODULE.register(self.data, self.args)

    def monday(self):
        self.clock = datetime(2026, 11, 9, 12, 0, tzinfo=MODULE.TZ)

    def test_monday_cleanup_and_rerun_keep_unrelated_recording(self):
        self.register()
        self.monday()
        self.assertEqual(MODULE.cleanup(self.data, True)["receipts"][0]["status"], "cleaned")
        self.assertFalse(self.recording.exists())
        self.assertFalse(self.artifacts.exists())
        self.assertEqual((self.unrelated / "recording.mp4").read_bytes(), b"other recording")
        self.assertEqual(MODULE.cleanup(self.data, True)["receipts"], [])
        self.assertEqual(json.loads(self.ledger.read_text())["receipts"][0]["status"], "cleaned")

    def test_not_due_until_following_monday(self):
        self.register()
        self.assertEqual(MODULE.cleanup(self.data, True)["receipts"][0]["status"], "not-due")
        self.assertTrue(self.output.exists())
        self.assertEqual(self.remote.call_count, 1)

    def test_dry_run_verifies_but_preserves_files(self):
        self.register()
        self.monday()
        self.assertEqual(MODULE.cleanup(self.data, False)["receipts"][0]["status"], "eligible")
        self.assertTrue(self.output.exists())
        self.assertTrue(self.recording.exists())
        self.assertEqual(self.data["receipts"][0]["status"], "delivered")

    def test_remote_unavailable_preserves_every_local_file(self):
        self.register()
        self.monday()
        self.remote.side_effect = ValueError("permission lost")
        self.assertEqual(MODULE.cleanup(self.data, True)["receipts"][0]["status"], "retained")
        self.assertTrue(self.output.exists())
        self.assertTrue((self.recording / "recording.mp4").exists())

    def test_failed_upload_cannot_register_a_receipt(self):
        self.remote.side_effect = ValueError("attachment missing")
        with self.assertRaises(ValueError):
            self.register()
        self.assertEqual(self.data["receipts"], [])
        self.assertFalse(self.ledger.exists())

    def test_changed_and_added_files_prevent_cleanup(self):
        self.register()
        self.monday()
        (self.recording / "recording.mp4").write_bytes(b"replacement")
        self.assertEqual(MODULE.cleanup(self.data, True)["receipts"][0]["status"], "retained")
        self.assertTrue(self.output.exists())
        (self.recording / "recording.mp4").write_bytes(b"original video")
        (self.artifacts / "keep.txt").write_text("new work")
        self.assertEqual(MODULE.cleanup(self.data, True)["receipts"][0]["status"], "retained")
        self.assertTrue(self.recording.exists())

    def test_later_codex_attachment_preserves_source(self):
        self.register()
        self.monday()
        self.not_sent.side_effect = ValueError("now sent to Codex")
        self.assertEqual(MODULE.cleanup(self.data, True)["receipts"][0]["status"], "retained")
        self.assertTrue(self.recording.exists())

    def test_symlink_and_root_directory_are_not_eligible(self):
        (self.recording / "outside").symlink_to(self.unrelated, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.register()
        self.assertTrue((self.unrelated / "recording.mp4").exists())
        self.args.recording = self.recordings
        with self.assertRaises(ValueError):
            self.register()

    def test_retry_after_partial_cleanup(self):
        self.register()
        self.monday()
        original = MODULE.remove_snapshot
        def fail_after_source(directory, snapshot):
            if directory == self.artifacts:
                raise OSError("simulated artifact removal failure")
            original(directory, snapshot)
        with patch.object(MODULE, "remove_snapshot", side_effect=fail_after_source):
            self.assertEqual(MODULE.cleanup(self.data, True)["receipts"][0]["status"], "retained")
        self.assertFalse(self.recording.exists())
        self.assertTrue(self.output.exists())
        reloaded = json.loads(self.ledger.read_text())
        self.assertEqual(MODULE.cleanup(reloaded, True)["receipts"][0]["status"], "cleaned")

    def test_reference_document_and_duplicate_delivery_rejected(self):
        self.args.document_id = MODULE.REFERENCE_DOC
        with self.assertRaises(ValueError):
            self.register()
        self.args.document_id = "newDoc"
        self.register()
        with self.assertRaises(ValueError):
            self.register()

    def test_remote_verification_requires_attached_token_and_equal_bytes(self):
        receipt = {"documentId": "newDoc", "blockId": "block", "fileToken": "videoToken",
                   "outputSha256": MODULE.digest(self.output)}
        xml = '<fragment><figure id="block"><source token="videoToken"/></figure></fragment>'
        def fake_cli(args, cwd=None):
            if args[1] == "+fetch":
                return {"document": {"document_id": "newDoc", "content": xml, "revision_id": 12}}
            (Path(cwd) / "remote.mp4").write_bytes(b"finished demo")
            return {}
        # Call the real implementation while mocking only the external CLI transport.
        with patch.object(MODULE, "cli", side_effect=fake_cli):
            verifier = self._real_remote
            self.assertTrue(verifier(receipt)["downloadSha256Matched"])
            receipt["outputSha256"] = "wrong"
            with self.assertRaises(ValueError):
                verifier(receipt)
            receipt["fileToken"] = "otherToken"
            with self.assertRaises(ValueError):
                verifier(receipt)

    _real_remote = staticmethod(MODULE.verify_remote)


if __name__ == "__main__":
    unittest.main()
