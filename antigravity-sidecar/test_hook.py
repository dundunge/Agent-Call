#!/usr/bin/env python3
"""Offline Stop hook tests; no Antigravity process or model call is needed."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).with_name("hook.py")


class StopHookTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agent-call-hook-")
        self.root = Path(self.temp.name)
        self.data = self.root / "sidecar" / "data"
        receipts = self.data / "receipts"
        receipts.mkdir(parents=True)
        self.conversation_id = "sample-conversation"
        self.request_id = "sample-request"
        (receipts / (self.request_id + ".json")).write_text(json.dumps({
            "requestId": self.request_id,
            "recipientTaskRef": self.conversation_id,
            "dispatchStatus": "CLI_ACCEPTED",
        }), encoding="utf-8")
        self.app_data = self.root / "app-data"
        self.transcript = (self.app_data / "brain" / self.conversation_id
                           / ".system_generated" / "logs" / "transcript.jsonl")
        self.transcript.parent.mkdir(parents=True)
        self.transcript.write_text("\n".join(json.dumps(item) for item in (
            {"type": "USER_INPUT", "status": "DONE",
             "content": "<USER_REQUEST>\n[agent-call requestId=sample-request]\nhi\n</USER_REQUEST>"},
            {"type": "PLANNER_RESPONSE", "status": "DONE",
             "content": "Hello! How can I help you today?"},
        )) + "\n", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def run_hook(self, conversation_id=None, fully_idle=True):
        payload = {
            "conversationId": conversation_id or self.conversation_id,
            "transcriptPath": str(self.transcript),
            "terminationReason": "model_stop",
            "fullyIdle": fully_idle,
            "modelName": "test-model",
        }
        completed = subprocess.run(
            [sys.executable, str(HOOK), "--data-dir", str(self.data),
             "--app-data-dir", str(self.app_data)],
            input=json.dumps(payload), text=True, capture_output=True, check=False,
        )
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(json.loads(completed.stdout), {"decision": ""})
        return self.data / "results" / (self.request_id + ".json")

    def test_correlated_stop_captures_reply(self):
        result_path = self.run_hook()
        result = json.loads(result_path.read_text())
        self.assertEqual(result["collectionStatus"], "AVAILABLE")
        self.assertEqual(result["agentOutcome"], "completed")
        self.assertEqual(result["response"], "Hello! How can I help you today?")

    def test_other_conversation_is_ignored(self):
        result_path = self.run_hook(conversation_id="unrelated-conversation")
        self.assertFalse(result_path.exists())

    def test_background_work_is_not_completed(self):
        result_path = self.run_hook(fully_idle=False)
        result = json.loads(result_path.read_text())
        self.assertEqual(result["collectionStatus"], "PENDING_BACKGROUND")
        self.assertEqual(result["agentOutcome"], "unknown")


if __name__ == "__main__":
    unittest.main()
