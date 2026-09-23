#!/usr/bin/env python3
"""Offline tests for the Antigravity sidecar bridge; no app or account required."""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

BRIDGE = Path(__file__).with_name("bridge.py")


class BridgeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agent-call-test-")
        self.root = Path(self.temp.name)
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        fake = bin_dir / "agentapi"
        fake.write_text(
            "#!/bin/sh\n"
            "printf '%s\\n' \"$1|$2|$3\" >> \"$FAKE_LOG\"\n"
            "if [ \"$1\" = get-conversation-metadata ] && [ \"$FAKE_FAIL_META\" = 1 ]; then\n"
            "  printf '{\"error\":\"simulated\"}\\n'\n"
            "  exit 0\n"
            "fi\n"
            "if [ \"$1\" = new-conversation ]; then\n"
            "  if [ \"$FAKE_NO_REF\" = 1 ]; then printf '{}\\n'; exit 0; fi\n"
            "  printf '{\"conversationId\":\"created-conversation\"}\\n'\n"
            "  exit 0\n"
            "fi\n"
            "if [ \"$1\" = send-message ] && [ \"$FAKE_FAIL_SEND\" = 1 ]; then\n"
            "  printf '{\"error\":\"simulated\"}\\n'\n"
            "else\n"
            "  printf '{}\\n'\n"
            "fi\n",
            encoding="utf-8",
        )
        fake.chmod(0o755)
        self.data_dir = self.root / "data"
        self.data_dir.mkdir()
        self.socket = self.data_dir / "agent-call.sock"
        self.log = self.root / "calls.log"
        self.env = os.environ.copy()
        self.env.update({
            "PATH": str(bin_dir) + os.pathsep + self.env.get("PATH", ""),
            "FAKE_LOG": str(self.log),
            "ANTIGRAVITY_EXECUTABLE_DATA_DIR": str(self.data_dir),
        })
        self.prompt = self.root / "prompt.txt"
        self.prompt.write_text("Inspect this sample file.", encoding="utf-8")
        self.server = None

    def tearDown(self):
        if self.server is not None:
            self.server.terminate()
            try:
                self.server.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.server.kill()
                self.server.wait(timeout=3)
            if self.server.stderr is not None:
                self.server.stderr.close()
        self.temp.cleanup()

    def start_server(self, fail_send=False, fail_metadata=False, no_ref=False):
        env = self.env.copy()
        if fail_send:
            env["FAKE_FAIL_SEND"] = "1"
        if fail_metadata:
            env["FAKE_FAIL_META"] = "1"
        if no_ref:
            env["FAKE_NO_REF"] = "1"
        self.server = subprocess.Popen(
            [sys.executable, str(BRIDGE), "serve"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        for _ in range(100):
            if self.socket.exists():
                return
            if self.server.poll() is not None:
                self.fail("bridge exited before creating its socket")
            time.sleep(0.02)
        self.fail("bridge did not create its socket")

    def command(self, action, *arguments):
        completed = subprocess.run(
            [sys.executable, str(BRIDGE), action, *arguments, "--socket", str(self.socket)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return completed.returncode, json.loads(completed.stdout)

    def send(self, request_id):
        return self.command(
            "send", "--request-id", request_id,
            "--conversation-id", "sample-conversation",
            "--prompt-file", str(self.prompt),
        )

    def test_send_receipt_and_idempotency(self):
        self.start_server()
        code, receipt = self.send("request-1")
        self.assertEqual(code, 0)
        self.assertEqual(receipt["dispatchStatus"], "CLI_ACCEPTED")
        self.assertFalse(receipt["nativeCompletionVerified"])
        self.assertFalse(receipt["desktopVisibilityVerified"])
        self.assertNotIn("digest", receipt)
        calls = self.log.read_text().splitlines()
        self.assertEqual(calls[0], "get-conversation-metadata|sample-conversation|")
        self.assertIn("send-message|sample-conversation|[agent-call requestId=request-1]", calls[1])
        self.assertEqual(calls[2], "Inspect this sample file.")

        code, repeated = self.send("request-1")
        self.assertEqual(code, 0)
        self.assertEqual(repeated["dispatchStatus"], "CLI_ACCEPTED")
        self.assertEqual(len(self.log.read_text().splitlines()), 3)
        code, status = self.command("status", "--request-id", "request-1")
        self.assertEqual(code, 0)
        self.assertEqual(status["dispatchStatus"], "CLI_ACCEPTED")

        self.prompt.write_text("Different text.", encoding="utf-8")
        code, conflict = self.send("request-1")
        self.assertEqual(code, 2)
        self.assertEqual(conflict["dispatchStatus"], "CONFLICT")

    def test_create_conversation_once(self):
        self.start_server()
        code, receipt = self.command(
            "create", "--request-id", "create-1", "--prompt-file", str(self.prompt),
        )
        self.assertEqual(code, 0)
        self.assertEqual(receipt["dispatchStatus"], "CLI_ACCEPTED")
        self.assertEqual(receipt["recipientTaskRef"], "created-conversation")
        self.assertFalse(receipt["nativeCompletionVerified"])
        self.assertFalse(receipt["desktopVisibilityVerified"])
        code, repeated = self.command(
            "create", "--request-id", "create-1", "--prompt-file", str(self.prompt),
        )
        self.assertEqual(code, 0)
        self.assertEqual(repeated["recipientTaskRef"], "created-conversation")
        calls = self.log.read_text().splitlines()
        self.assertIn("new-conversation|[agent-call requestId=create-1]", calls[0])
        self.assertEqual(len(calls), 2)

    def test_status_resolves_create_from_sidecar_event(self):
        self.start_server(no_ref=True)
        code, receipt = self.command(
            "create", "--request-id", "create-event-1", "--prompt-file", str(self.prompt),
        )
        self.assertEqual(code, 2)
        self.assertEqual(receipt["dispatchStatus"], "CLI_ACCEPTED_NO_REF")
        events = self.root / "events"
        events.mkdir()
        (events / "20260923_061704.json").write_text(json.dumps({
            "error": "",
            "payload": {"newConversation": {
                "prompt": "[agent-call requestId=create-event-1]\nInspect this sample file.",
                "conversationId": "from-event",
            }},
        }), encoding="utf-8")
        code, status = self.command("status", "--request-id", "create-event-1")
        self.assertEqual(code, 0)
        self.assertEqual(status["dispatchStatus"], "CLI_ACCEPTED")
        self.assertEqual(status["recipientTaskRef"], "from-event")

    def test_uncertain_send_is_not_repeated(self):
        self.start_server(fail_send=True)
        code, receipt = self.send("request-2")
        self.assertEqual(code, 2)
        self.assertEqual(receipt["dispatchStatus"], "DISPATCH_UNKNOWN")
        code, repeated = self.send("request-2")
        self.assertEqual(code, 2)
        self.assertEqual(repeated["dispatchStatus"], "DISPATCH_UNKNOWN")
        self.assertEqual(len(self.log.read_text().splitlines()), 3)

    def test_metadata_failure_does_not_send(self):
        self.start_server(fail_metadata=True)
        code, receipt = self.send("request-3")
        self.assertEqual(code, 2)
        self.assertEqual(receipt["dispatchStatus"], "REJECTED")
        self.assertEqual(self.log.read_text().splitlines(), [
            "get-conversation-metadata|sample-conversation|",
        ])

    def test_missing_sidecar_cannot_deliver(self):
        code, receipt = self.send("request-4")
        self.assertEqual(code, 2)
        self.assertEqual(receipt["dispatchStatus"], "REJECTED")
        self.assertFalse(self.log.exists())

    def test_collect_reads_hook_result(self):
        self.start_server()
        self.send("request-result")
        code, pending = self.command("collect", "--request-id", "request-result")
        self.assertEqual(code, 2)
        self.assertEqual(pending["collectionStatus"], "NOT_READY")
        results = self.data_dir / "results"
        results.mkdir()
        (results / "request-result.json").write_text(json.dumps({
            "collectionStatus": "AVAILABLE",
            "agentOutcome": "completed",
            "response": "Hello!",
        }), encoding="utf-8")
        code, result = self.command("collect", "--request-id", "request-result")
        self.assertEqual(code, 0)
        self.assertEqual(result["response"], "Hello!")


if __name__ == "__main__":
    unittest.main()
