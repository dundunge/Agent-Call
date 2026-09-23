import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location("grok_bridge", Path(__file__).with_name("bridge.py"))
bridge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bridge)

SESSION = "12345678-1234-1234-1234-123456789abc"


class GrokBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app = self.root / "app"
        self.state = self.root / "state"
        self.calls = []
        self.patch_app = patch.object(bridge, "app_data_dir", return_value=self.app)
        self.patch_state = patch.object(bridge, "state_dir", return_value=self.state)
        self.patch_api = patch.object(bridge, "api_request", side_effect=self.fake_api)
        for item in (self.patch_app, self.patch_state, self.patch_api):
            item.start()
            self.addCleanup(item.stop)

    def fake_api(self, method, route, body=None, timeout=20):
        self.calls.append((method, route, body))
        if method == "GET":
            return 200, [{"id": SESSION, "title": "联调", "projectId": None}]
        return 200, {"ok": True, "status": "turn_started", "sessionId": SESSION}

    def write_journal(self, messages):
        path = self.app / "sessions" / SESSION / "messages.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(messages), encoding="utf-8")

    def test_send_once_and_collect_local_reply(self):
        self.write_journal([{"id": "old", "role": "user", "content": "联调"}])
        first = bridge.send(SESSION, "req-1", "hi")
        self.assertEqual(first["delivery"], "accepted")
        self.assertEqual(first["nativeStatus"], "turn_started")
        self.assertEqual(len([x for x in self.calls if x[0] == "POST"]), 1)
        self.assertEqual(bridge.send(SESSION, "req-1", "hi"), first)
        self.assertEqual(len([x for x in self.calls if x[0] == "POST"]), 1)
        self.assertEqual(bridge.send(SESSION, "req-1", "different")["status"], "conflict")
        self.write_journal([{"id": "old", "role": "user", "content": "联调"},
                            {"id": "u1", "role": "user", "content": "hi"},
                            {"id": "a1", "role": "assistant", "content": "你好", "isError": False}])
        observed = bridge.observe("req-1", True)
        self.assertEqual(observed["collectionStatus"], "reply_observed")
        self.assertEqual(observed["reply"], "你好")
        self.assertFalse(observed["nativeCompletionVerified"])
        self.assertEqual(observed["resultSource"], "version_specific_local_journal_read_only")

    def test_requires_existing_session(self):
        with patch.object(bridge, "api_request", return_value=(200, [])):
            self.assertEqual(bridge.send(SESSION, "req-2", "hi")["status"], "not_found")

    def test_post_error_is_not_retried(self):
        self.write_journal([])
        def failed_api(method, route, body=None, timeout=20):
            if method == "GET":
                return 200, [{"id": SESSION}]
            raise TimeoutError("uncertain delivery")
        with patch.object(bridge, "api_request", side_effect=failed_api):
            first = bridge.send(SESSION, "req-3", "hi")
            second = bridge.send(SESSION, "req-3", "hi")
        self.assertEqual(first["delivery"], "unknown")
        self.assertEqual(second, first)
        self.assertEqual(first["nativeStatus"], "dispatch_unknown")

    def test_api_rejects_non_loopback_url(self):
        self.app.mkdir()
        (self.app / "session-api.json").write_text(json.dumps({"url": "https://example.com", "token": "test-token"}))
        with self.assertRaises(ValueError):
            bridge.api_config()


if __name__ == "__main__":
    unittest.main()
