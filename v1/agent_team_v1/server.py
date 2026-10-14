from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from .adapters import MockAdapter
from .models import AcceptanceResult, AgentOutcome
from .service import ControlPlane, ControlPlaneError
from .store import SQLiteStore


class ApiHandler(BaseHTTPRequestHandler):
    server_version = "AgentTeamV1/0.1"

    def _plane(self) -> ControlPlane:
        return self.server.control_plane  # type: ignore[attr-defined]

    def _json(self, status: int, payload: object) -> None:
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 200_000:
            raise ValueError("request body too large")
        raw = self.rfile.read(length)
        value = json.loads(raw or b"{}")
        if not isinstance(value, dict):
            raise ValueError("request body must be an object")
        return value

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/") or "/"
        try:
            if path in {"/", "/index.html", "/app.js", "/simulation.js", "/styles.css"} or path.startswith("/vendor/"):
                return self._static(path)
            if path == "/health":
                return self._json(200, {"status": "ok", "service": "agent-team-v1"})
            if path == "/tasks":
                return self._json(200, {"tasks": [task.to_dict() for task in self._plane().store.list()]})
            if path.startswith("/tasks/") and path.endswith("/events"):
                task_id = unquote(path.split("/", 3)[2])
                return self._json(200, {"taskId": task_id, "events": self._plane().events(task_id)})
            if path.startswith("/tasks/"):
                task_id = unquote(path.split("/", 2)[2])
                return self._json(200, self._plane().status(task_id).to_dict())
            return self._json(404, {"error": "not_found"})
        except ControlPlaneError as exc:
            return self._json(404, {"error": type(exc).__name__, "message": str(exc)})

    def _static(self, path: str) -> None:
        web_root = Path(__file__).with_name("web").resolve()
        names = {"/": "index.html", "/index.html": "index.html", "/app.js": "app.js", "/simulation.js": "simulation.js", "/styles.css": "styles.css"}
        if path in names:
            file_path = web_root / names[path]
        elif path.startswith("/vendor/"):
            file_path = (web_root / path.removeprefix("/")).resolve()
        else:
            return self._json(404, {"error": "static_not_found"})
        if web_root not in file_path.parents or not file_path.is_file():
            return self._json(404, {"error": "static_not_found"})
        content_types = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".txt": "text/plain; charset=utf-8"}
        body = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_types[file_path.suffix])
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/")
        try:
            body = self._body()
            if path == "/tasks":
                task = self._plane().create_task(
                    task_id=str(body["taskId"]),
                    provider=str(body["provider"]),
                    adapter=str(body.get("adapter", "agent-call")),
                    workspace=str(body["workspace"]),
                    objective=str(body["objective"]),
                    prompt=str(body["prompt"]),
                    acceptance_criteria=tuple(str(item) for item in body["acceptanceCriteria"]),
                    attempt_id=body.get("attemptId"),
                    request_id=body.get("requestId"),
                )
                return self._json(201, task.to_dict())
            if not path.startswith("/tasks/"):
                return self._json(404, {"error": "not_found"})
            parts = path.split("/")
            if len(parts) != 4:
                return self._json(404, {"error": "not_found"})
            task_id, action = unquote(parts[2]), parts[3]
            if action == "dispatch":
                return self._json(200, self._plane().dispatch(task_id, MockAdapter()).to_dict())
            if action == "observe":
                return self._json(
                    200,
                    self._plane().observe(
                        task_id,
                        outcome=AgentOutcome(body["outcome"]),
                        response=body.get("response"),
                        error=body.get("error"),
                    ).to_dict(),
                )
            if action == "accept":
                return self._json(
                    200,
                    self._plane().accept(
                        task_id,
                        result=AcceptanceResult(body["result"]),
                        evidence=tuple(str(item) for item in body["evidence"]),
                    ).to_dict(),
                )
            return self._json(404, {"error": "not_found"})
        except (ControlPlaneError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            return self._json(400, {"error": type(exc).__name__, "message": str(exc)})

    def log_message(self, format: str, *args: object) -> None:
        return


def serve(db: str, host: str = "127.0.0.1", port: int = 8766) -> None:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("V1 server binds only to loopback by default")
    httpd = ThreadingHTTPServer((host, port), ApiHandler)
    httpd.control_plane = ControlPlane(SQLiteStore(db))  # type: ignore[attr-defined]
    print(json.dumps({"status": "listening", "host": host, "port": port}), flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
