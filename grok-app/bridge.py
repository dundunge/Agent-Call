#!/usr/bin/env python3
"""Send to an existing Grok App conversation through its loopback Session API.

The optional reply reader uses Grok App's local journal, not an official result
endpoint. It cannot prove that a turn has finished.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
SESSION_ID = re.compile(r"^[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$")
MAX_JOURNAL_BYTES = 16 * 1024 * 1024


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def app_data_dir():
    override = os.environ.get("GROK_APP_DATA_DIR")
    if override:
        return Path(override).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/com.grokapp.grok-app"
    raise ValueError("set GROK_APP_DATA_DIR for this platform")


def state_dir():
    return Path(os.environ.get("AGENT_CALL_GROK_STATE_DIR", "~/.local/state/agent-call/grok-app")).expanduser()


def require_id(value, pattern, label):
    if not pattern.fullmatch(value or ""):
        raise ValueError(f"invalid {label}")
    return value


def receipt_file(request_id):
    return state_dir() / (require_id(request_id, REQUEST_ID, "request ID") + ".json")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, value, exclusive=False):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if exclusive:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.write("\n")
        return
    fd, name = tempfile.mkstemp(prefix=".receipt-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.write("\n")
        os.chmod(name, 0o600)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise ValueError("session API redirect refused")


def api_config():
    config = read_json(app_data_dir() / "session-api.json")
    url = config.get("url", "")
    parsed = urllib.parse.urlparse(url)
    if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or not parsed.port
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment
            or parsed.username or parsed.password):
        raise ValueError("session API URL must be plain HTTP on 127.0.0.1")
    token = config.get("token")
    if not isinstance(token, str) or not token:
        raise ValueError("session API token missing")
    return url.rstrip("/"), token


def api_request(method, route, body=None, timeout=20):
    url, token = api_config()
    headers = {"Authorization": "Bearer " + token}
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url + route, data=data, headers=headers, method=method)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        try:
            payload = json.loads(error.read(4096))
        except (UnicodeError, json.JSONDecodeError):
            payload = {}
        return error.code, payload


def journal_messages(session_id):
    path = app_data_dir() / "sessions" / require_id(session_id, SESSION_ID, "session ID") / "messages.json"
    if not path.exists():
        return []
    if path.stat().st_size > MAX_JOURNAL_BYTES:
        raise ValueError("local journal exceeds size limit")
    messages = read_json(path)
    if not isinstance(messages, list):
        raise ValueError("invalid local journal")
    return messages


def public_receipt(receipt):
    return {key: value for key, value in receipt.items() if key not in ("requestDigest", "promptDigest", "seenMessageIds")}


def list_sessions():
    code, data = api_request("GET", "/v1/sessions?include_archived=false", timeout=5)
    if code != 200 or not isinstance(data, list):
        return {"status": "error", "httpStatus": code}
    return {"status": "ok", "sessions": [
        {key: item.get(key) for key in ("id", "title", "projectId", "projectName", "updatedAt")}
        for item in data if isinstance(item, dict)
    ]}


def send(session_id, request_id, prompt):
    require_id(session_id, SESSION_ID, "session ID")
    require_id(request_id, REQUEST_ID, "request ID")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt.encode("utf-8")) > 40000:
        raise ValueError("prompt must contain 1-40000 UTF-8 bytes")
    digest = hashlib.sha256((session_id + "\0" + prompt).encode("utf-8")).hexdigest()
    path = receipt_file(request_id)
    if path.exists():
        old = read_json(path)
        return {"status": "conflict", "requestId": request_id} if old.get("requestDigest") != digest else public_receipt(old)

    code, sessions = api_request("GET", "/v1/sessions?include_archived=false", timeout=5)
    if code != 200 or not isinstance(sessions, list):
        return {"status": "preflight_failed", "httpStatus": code}
    if not any(isinstance(x, dict) and x.get("id") == session_id for x in sessions):
        return {"status": "not_found", "sessionId": session_id}

    before = journal_messages(session_id)
    receipt = {
        "protocol": "agent-call/v1", "kind": "receipt", "requestId": request_id,
        "recipientTaskRef": session_id, "delivery": "unknown", "nativeStatus": "not_dispatched",
        "createdAt": utc_now(), "requestDigest": digest,
        "promptDigest": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "seenMessageIds": [x.get("id") for x in before if isinstance(x, dict) and isinstance(x.get("id"), str)],
    }
    try:
        write_json(path, receipt, exclusive=True)
    except FileExistsError:
        old = read_json(path)
        return {"status": "conflict", "requestId": request_id} if old.get("requestDigest") != digest else public_receipt(old)

    # Never auto-retry an uncertain POST. The native idempotency key is the
    # request ID, so a human can reconcile the same attempt if necessary.
    receipt["nativeStatus"] = "dispatch_unknown"
    try:
        code, result = api_request("POST", f"/v1/sessions/{session_id}/turns",
                                   {"prompt": prompt, "idempotencyKey": request_id})
        receipt["httpStatus"] = code
        receipt["nativeStatus"] = result.get("status", "unknown") if isinstance(result, dict) else "unknown"
        if code in (200, 202) and receipt["nativeStatus"] in ("turn_started", "queued"):
            receipt["delivery"] = "accepted"
        elif code in (400, 404, 409):
            receipt["delivery"] = "rejected"
    except (OSError, ValueError, TimeoutError):
        pass
    write_json(path, receipt)
    return public_receipt(receipt)


def observe(request_id, include_reply):
    path = receipt_file(request_id)
    if not path.exists():
        return {"status": "not_found", "requestId": request_id}
    receipt = read_json(path)
    messages = journal_messages(receipt["recipientTaskRef"])
    seen = set(receipt.get("seenMessageIds", []))
    prompt_digest = receipt.get("promptDigest")
    candidates = [i for i, x in enumerate(messages)
                  if isinstance(x, dict) and x.get("role") == "user" and x.get("id") not in seen
                  and hashlib.sha256(str(x.get("content", "")).encode("utf-8")).hexdigest() == prompt_digest]
    output = {"requestId": request_id, "recipientTaskRef": receipt["recipientTaskRef"],
              "delivery": receipt.get("delivery", "unknown"), "nativeStatus": receipt.get("nativeStatus", "unknown"),
              "userMessageObserved": len(candidates) == 1, "nativeCompletionVerified": False}
    if len(candidates) > 1:
        output["collectionStatus"] = "ambiguous_user_messages"
        return output
    if not candidates:
        output["collectionStatus"] = "not_ready"
        return output
    index = candidates[0]
    output["userMessageId"] = messages[index].get("id")
    following = messages[index + 1:]
    next_user = next((i for i, x in enumerate(following) if isinstance(x, dict) and x.get("role") == "user"), len(following))
    replies = [x for x in following[:next_user] if isinstance(x, dict) and x.get("role") == "assistant"]
    if not replies:
        output["collectionStatus"] = "not_ready"
        return output
    output["collectionStatus"] = "reply_observed"
    output["replyMessageId"] = replies[-1].get("id")
    output["replyIsError"] = replies[-1].get("isError") is True
    output["resultSource"] = "version_specific_local_journal_read_only"
    if include_reply:
        output["reply"] = replies[-1].get("content", "")
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    sending = sub.add_parser("send")
    sending.add_argument("--session-id", required=True)
    sending.add_argument("--request-id", required=True)
    prompt_source = sending.add_mutually_exclusive_group(required=True)
    prompt_source.add_argument("--prompt")
    prompt_source.add_argument("--prompt-file", type=Path)
    for name in ("status", "collect"):
        sub.add_parser(name).add_argument("--request-id", required=True)
    args = parser.parse_args()
    try:
        if args.command == "list":
            result = list_sessions()
        elif args.command == "send":
            prompt = args.prompt if args.prompt_file is None else args.prompt_file.read_text(encoding="utf-8")
            result = send(args.session_id, args.request_id, prompt)
        else:
            result = observe(args.request_id, args.command == "collect")
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        result = {"status": "error", "error": type(error).__name__}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
