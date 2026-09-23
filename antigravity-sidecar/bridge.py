#!/usr/bin/env python3
"""Local Unix-socket bridge to Antigravity's sidecar-only agentapi.

The server runs inside an Antigravity sidecar, where agentapi and
ANTIGRAVITY_EXECUTABLE_DATA_DIR are supplied by the host. The client runs
from Codex or a terminal. This bridge creates a conversation or sends to one;
it does not claim native turn completion or GUI visibility.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import socketserver
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

MAX_LINE_BYTES = 65536
MAX_PROMPT_BYTES = 40000
ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
SOCKET_NAME = "agent-call.sock"


class BridgeUnavailable(Exception):
    """The request could not reach the sidecar socket."""


def now_utc():
    return datetime.now(timezone.utc).isoformat()


def default_socket():
    return Path.home() / ".gemini/antigravity/sidecar_data/agent-call/data" / SOCKET_NAME


def valid_id(value, label):
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise ValueError("%s must contain 1-128 letters, digits, dots, dashes or underscores" % label)
    return value


def receipt_path(data_dir, request_id):
    return data_dir / "receipts" / (valid_id(request_id, "requestId") + ".json")


def load_receipt(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {"dispatchStatus": "RECOVERY_REQUIRED", "error": "receipt cannot be read"}
    return value if isinstance(value, dict) else {"dispatchStatus": "RECOVERY_REQUIRED", "error": "invalid receipt"}


def replace_json(path, value):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".receipt-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def create_receipt(path, value):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, separators=(",", ":"))
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def call_agentapi(agentapi, arguments, timeout_seconds):
    try:
        completed = subprocess.run(
            [agentapi] + arguments,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, "timeout", None
    except OSError:
        return False, "launch failed", None
    if completed.returncode != 0:
        return False, "nonzero exit", None
    try:
        response = json.loads(completed.stdout)
    except json.JSONDecodeError:
        response = None
    if isinstance(response, dict):
        native_status = str(response.get("status", "")).upper()
        if response.get("error") or response.get("success") is False or native_status in ("ERROR", "FAILED"):
            return False, "native error", None
    return True, "ok", response if response is not None else completed.stdout.strip()


def conversation_ref(response):
    candidates = [response]
    if isinstance(response, dict):
        candidates.extend(response.get(key) for key in ("conversation", "data"))
    for candidate in candidates:
        if isinstance(candidate, dict):
            for key in ("conversation_id", "conversationId", "id"):
                value = candidate.get(key)
                if isinstance(value, str) and ID_PATTERN.fullmatch(value):
                    return value
        elif isinstance(candidate, str) and ID_PATTERN.fullmatch(candidate):
            return candidate
    return None


def conversation_ref_from_event(data_dir, request_id):
    """Best-effort lookup in the documented sidecar event directory."""
    events_dir = data_dir.parent / "events"
    if not events_dir.is_dir():
        return None
    marker = "[agent-call requestId=%s]\n" % request_id
    for path in sorted(events_dir.glob("*.json"), reverse=True)[:100]:
        try:
            if path.stat().st_size > 200000:
                continue
            event = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(event, dict) or event.get("error"):
            continue
        payload = event.get("payload")
        details = payload.get("newConversation") if isinstance(payload, dict) else None
        if isinstance(details, dict) and str(details.get("prompt", "")).startswith(marker):
            return conversation_ref(details)
    return None


def dispatch(data_dir, agentapi, request):
    if request.get("kind") in ("status", "collect"):
        kind = request["kind"]
        path = receipt_path(data_dir, request.get("requestId"))
        if not path.exists():
            return {"dispatchStatus": "NOT_FOUND"}
        receipt = load_receipt(path)
        if receipt.get("dispatchStatus") == "RECOVERY_REQUIRED":
            return receipt
        if receipt.get("dispatchStatus") == "CLI_ACCEPTED_NO_REF" and receipt.get("kind") == "create":
            ref = conversation_ref_from_event(data_dir, receipt["requestId"])
            if ref:
                receipt["recipientTaskRef"] = ref
                receipt["dispatchStatus"] = "CLI_ACCEPTED"
                receipt["resolvedAt"] = now_utc()
                replace_json(path, receipt)
        result_path = data_dir / "results" / (receipt["requestId"] + ".json")
        if kind == "collect":
            if not result_path.exists():
                return {"collectionStatus": "NOT_READY", "requestId": receipt["requestId"]}
            return load_receipt(result_path)
        if result_path.exists():
            result = load_receipt(result_path)
            receipt["collectionStatus"] = result.get("collectionStatus", "UNKNOWN")
            receipt["agentOutcome"] = result.get("agentOutcome", "unknown")
            receipt["nativeCompletionVerified"] = result.get("fullyIdle") is True
        return {key: value for key, value in receipt.items() if key != "digest"}

    kind = request.get("kind")
    if kind not in ("create", "send"):
        raise ValueError("kind must be create, send or status")
    request_id = valid_id(request.get("requestId"), "requestId")
    conversation_id = valid_id(request.get("conversationId"), "conversationId") if kind == "send" else None
    prompt = request.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("prompt must be non-empty UTF-8 text")
    if len(prompt.encode("utf-8")) > MAX_PROMPT_BYTES:
        raise ValueError("prompt is too large")

    digest = hashlib.sha256((kind + "\0" + (conversation_id or "") + "\0" + prompt).encode("utf-8")).hexdigest()
    path = receipt_path(data_dir, request_id)
    if path.exists():
        previous = load_receipt(path)
        if previous.get("dispatchStatus") == "RECOVERY_REQUIRED":
            return previous
        if previous.get("digest") != digest:
            return {"dispatchStatus": "CONFLICT", "requestId": request_id}
        return {key: value for key, value in previous.items() if key != "digest"}

    if kind == "send":
        # Metadata is read-only and checks that this sidecar can reach the bound conversation.
        metadata_ok, _, _ = call_agentapi(agentapi, ["get-conversation-metadata", conversation_id], 15)
        if not metadata_ok:
            return {"dispatchStatus": "REJECTED", "requestId": request_id,
                    "error": "conversation metadata check failed; no prompt was sent"}

    receipt = {
        "kind": kind,
        "requestId": request_id,
        "recipientTaskRef": conversation_id,
        "dispatchStatus": "DISPATCH_UNKNOWN",
        "nativeCompletionVerified": False,
        "desktopVisibilityVerified": False,
        "createdAt": now_utc(),
        "digest": digest,
    }
    try:
        create_receipt(path, receipt)
    except FileExistsError:
        previous = load_receipt(path)
        if previous.get("dispatchStatus") == "RECOVERY_REQUIRED":
            return previous
        if previous.get("digest") != digest:
            return {"dispatchStatus": "CONFLICT", "requestId": request_id}
        return {key: value for key, value in previous.items() if key != "digest"}

    visible_prompt = "[agent-call requestId=%s]\n%s" % (request_id, prompt)
    arguments = (["send-message", conversation_id, visible_prompt] if kind == "send"
                 else ["new-conversation", visible_prompt])
    sent, reason, native_response = call_agentapi(agentapi, arguments, 60)
    if sent:
        if kind == "create":
            receipt["recipientTaskRef"] = (conversation_ref(native_response)
                                           or conversation_ref_from_event(data_dir, request_id))
            receipt["dispatchStatus"] = "CLI_ACCEPTED" if receipt["recipientTaskRef"] else "CLI_ACCEPTED_NO_REF"
        else:
            receipt["dispatchStatus"] = "CLI_ACCEPTED"
    else:
        receipt["error"] = arguments[0] + " " + reason + "; reconcile in Antigravity before retrying"
    receipt["observedAt"] = now_utc()
    replace_json(path, receipt)
    return {key: value for key, value in receipt.items() if key != "digest"}


class BridgeHandler(socketserver.StreamRequestHandler):
    def handle(self):
        raw = self.rfile.readline(MAX_LINE_BYTES + 1)
        if len(raw) > MAX_LINE_BYTES:
            response = {"dispatchStatus": "REJECTED", "error": "request is too large"}
        else:
            try:
                request = json.loads(raw.decode("utf-8"))
                if not isinstance(request, dict):
                    raise ValueError("request must be a JSON object")
                response = dispatch(self.server.data_dir, self.server.agentapi, request)
            except (ValueError, UnicodeError, json.JSONDecodeError) as error:
                response = {"dispatchStatus": "REJECTED", "error": str(error)}
        self.wfile.write((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))


def serve():
    raw_dir = os.environ.get("ANTIGRAVITY_EXECUTABLE_DATA_DIR")
    if not raw_dir or not Path(raw_dir).is_absolute():
        raise SystemExit("ANTIGRAVITY_EXECUTABLE_DATA_DIR is required inside the sidecar")
    agentapi = shutil.which("agentapi")
    if not agentapi:
        raise SystemExit("agentapi is unavailable; run this server as an Antigravity sidecar")
    data_dir = Path(raw_dir)
    data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    address = data_dir / SOCKET_NAME
    if address.is_symlink():
        raise SystemExit("refusing a symlink at the socket path")
    if address.exists():
        if not stat.S_ISSOCK(address.lstat().st_mode):
            raise SystemExit("refusing a non-socket at the socket path")
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            probe.settimeout(1)
            probe.connect(str(address))
        except (OSError, socket.timeout):
            address.unlink()
        else:
            raise SystemExit("bridge already running")
        finally:
            probe.close()
    with socketserver.UnixStreamServer(str(address), BridgeHandler) as server:
        server.data_dir = data_dir
        server.agentapi = agentapi
        os.chmod(address, 0o600)
        try:
            server.serve_forever(poll_interval=0.5)
        finally:
            address.unlink(missing_ok=True)


def client(address, request):
    payload = (json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8")
    if len(payload) > MAX_LINE_BYTES:
        raise ValueError("request is too large")
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        connection.settimeout(75)
        try:
            connection.connect(str(address))
        except OSError as error:
            raise BridgeUnavailable("sidecar socket is unavailable") from error
        connection.sendall(payload)
        with connection.makefile("rb") as stream:
            response = stream.readline(MAX_LINE_BYTES + 1)
        if not response or len(response) > MAX_LINE_BYTES:
            raise OSError("invalid bridge response")
        return json.loads(response.decode("utf-8"))
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("serve")
    create = actions.add_parser("create")
    create.add_argument("--request-id", required=True)
    create.add_argument("--prompt-file", type=Path, required=True)
    send = actions.add_parser("send")
    send.add_argument("--request-id", required=True)
    send.add_argument("--conversation-id", required=True)
    send.add_argument("--prompt-file", type=Path, required=True)
    status = actions.add_parser("status")
    status.add_argument("--request-id", required=True)
    collect = actions.add_parser("collect")
    collect.add_argument("--request-id", required=True)
    for action in (create, send, status, collect):
        action.add_argument("--socket", type=Path, default=default_socket())
    args = parser.parse_args()
    if args.action == "serve":
        serve()
        return
    if args.action in ("create", "send"):
        try:
            prompt = args.prompt_file.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            print(json.dumps({"dispatchStatus": "REJECTED", "error": "prompt file cannot be read"}))
            sys.exit(2)
        request = {"kind": args.action, "requestId": args.request_id, "prompt": prompt}
        if args.action == "send":
            request["conversationId"] = args.conversation_id
    else:
        request = {"kind": args.action, "requestId": args.request_id}
    try:
        response = client(args.socket, request)
    except BridgeUnavailable as error:
        response = {"dispatchStatus": "REJECTED" if args.action in ("create", "send") else "STATUS_UNAVAILABLE",
                    "error": str(error)}
    except ValueError as error:
        response = {"dispatchStatus": "REJECTED", "error": str(error)}
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        response = {"dispatchStatus": "DISPATCH_UNKNOWN", "error": str(error)}
    print(json.dumps(response, ensure_ascii=False))
    if (response.get("collectionStatus") != "AVAILABLE" if args.action == "collect"
            else response.get("dispatchStatus") != "CLI_ACCEPTED"):
        sys.exit(2)


if __name__ == "__main__":
    main()
