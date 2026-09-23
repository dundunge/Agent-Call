#!/usr/bin/env python3
"""Capture a correlated Antigravity Stop event without changing agent control.

Configured as a global Stop hook, this script ignores conversations that have
no matching agent-call receipt. It stores only a compact result for a matching
request. The Hook contract and transcript path are documented by Antigravity.
"""

import argparse
import json
import re
import sys
from pathlib import Path

from bridge import ID_PATTERN, load_receipt, now_utc, replace_json

HOOK_LIMIT = 1000000
TRANSCRIPT_TAIL_BYTES = 2000000
MARKER = re.compile(r"\[agent-call requestId=([A-Za-z0-9._-]{1,128})\]\n")


def default_data_dir():
    return Path.home() / ".gemini/antigravity/sidecar_data/agent-call/data"


def default_app_data_dir():
    return Path.home() / ".gemini/antigravity"


def read_last_turn(transcript_path):
    request_id = None
    response = None
    with transcript_path.open("rb") as stream:
        size = stream.seek(0, 2)
        offset = max(0, size - TRANSCRIPT_TAIL_BYTES)
        stream.seek(offset)
        if offset:
            stream.readline()
        for raw in stream:
            try:
                step = json.loads(raw)
            except (UnicodeError, json.JSONDecodeError):
                continue
            if not isinstance(step, dict):
                continue
            if step.get("type") == "USER_INPUT":
                match = MARKER.search(str(step.get("content", "")))
                request_id = match.group(1) if match else None
                response = None
            elif (request_id and step.get("type") == "PLANNER_RESPONSE"
                  and step.get("status") == "DONE"):
                response = step.get("content") if isinstance(step.get("content"), str) else None
    return request_id, response


def capture(payload, data_dir, app_data_dir):
    conversation_id = payload.get("conversationId")
    if not isinstance(conversation_id, str) or not ID_PATTERN.fullmatch(conversation_id):
        return
    receipts_dir = data_dir / "receipts"
    if not receipts_dir.is_dir():
        return
    matching = {}
    for path in receipts_dir.glob("*.json"):
        receipt = load_receipt(path)
        if (receipt.get("recipientTaskRef") == conversation_id
                and receipt.get("dispatchStatus") == "CLI_ACCEPTED"):
            matching[receipt.get("requestId")] = receipt
    if not matching:
        return
    expected = (app_data_dir / "brain" / conversation_id / ".system_generated"
                / "logs" / "transcript.jsonl").resolve()
    supplied = payload.get("transcriptPath")
    if not isinstance(supplied, str) or Path(supplied).expanduser().resolve() != expected:
        return
    if not expected.is_file():
        return
    request_id, response = read_last_turn(expected)
    if request_id not in matching:
        return
    fully_idle = payload.get("fullyIdle") is True
    reason = payload.get("terminationReason")
    error_present = bool(payload.get("error"))
    if error_present or reason == "error":
        outcome = "failed"
    elif fully_idle and reason == "model_stop" and response is not None:
        outcome = "completed"
    else:
        outcome = "unknown"
    result = {
        "collectionStatus": "AVAILABLE" if fully_idle else "PENDING_BACKGROUND",
        "requestId": request_id,
        "recipientTaskRef": conversation_id,
        "agentOutcome": outcome,
        "response": response,
        "terminationReason": reason,
        "fullyIdle": fully_idle,
        "nativeCompletionVerified": fully_idle,
        "errorPresent": error_present,
        "modelName": payload.get("modelName"),
        "capturedAt": now_utc(),
    }
    replace_json(data_dir / "results" / (request_id + ".json"), result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=default_data_dir())
    parser.add_argument("--app-data-dir", type=Path, default=default_app_data_dir())
    args = parser.parse_args()
    try:
        raw = sys.stdin.buffer.read(HOOK_LIMIT + 1)
        if len(raw) <= HOOK_LIMIT:
            payload = json.loads(raw)
            if isinstance(payload, dict):
                capture(payload, args.data_dir, args.app_data_dir)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        pass
    # The Stop hook observes the run; it must never force another iteration.
    print('{"decision":""}')


if __name__ == "__main__":
    main()
