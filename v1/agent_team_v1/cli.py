from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .adapters import MockAdapter
from .models import AcceptanceResult, AgentOutcome, DeliveryStatus
from .server import serve
from .service import ControlPlane, ControlPlaneError
from .store import SQLiteStore


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Agent Team V1 provider-neutral control plane")
    root.add_argument("--db", default=".agent-team-v1/state.sqlite3", help="SQLite ledger path")
    commands = root.add_subparsers(dest="command", required=True)

    commands.add_parser("init")
    create = commands.add_parser("create")
    for flag in ("task-id", "provider", "adapter", "workspace", "objective", "prompt"):
        create.add_argument(f"--{flag}", required=True)
    create.add_argument("--acceptance", action="append", required=True)
    create.add_argument("--attempt-id")
    create.add_argument("--request-id")

    dispatch = commands.add_parser("dispatch")
    dispatch.add_argument("--task-id", required=True)
    dispatch.add_argument("--mode", choices=("mock",), default="mock")

    for name in ("status", "events"):
        command = commands.add_parser(name)
        command.add_argument("--task-id", required=True)

    observe = commands.add_parser("observe")
    observe.add_argument("--task-id", required=True)
    observe.add_argument("--outcome", choices=[item.value for item in AgentOutcome], required=True)
    observe.add_argument("--response")
    observe.add_argument("--error")

    accept = commands.add_parser("accept")
    accept.add_argument("--task-id", required=True)
    accept.add_argument("--result", choices=[AcceptanceResult.PASSED.value, AcceptanceResult.FAILED.value], required=True)
    accept.add_argument("--evidence", action="append", required=True)

    server = commands.add_parser("serve")
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=8766)
    return root


def emit(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "serve":
        serve(args.db, args.host, args.port)
        return 0
    plane = ControlPlane(SQLiteStore(args.db))
    try:
        if args.command == "init":
            emit({"status": "initialized", "db": str(Path(args.db).resolve())})
        elif args.command == "create":
            emit(
                plane.create_task(
                    task_id=args.task_id,
                    provider=args.provider,
                    adapter=args.adapter,
                    workspace=args.workspace,
                    objective=args.objective,
                    prompt=args.prompt,
                    acceptance_criteria=tuple(args.acceptance),
                    attempt_id=args.attempt_id,
                    request_id=args.request_id,
                ).to_dict()
            )
        elif args.command == "dispatch":
            emit(plane.dispatch(args.task_id, MockAdapter()).to_dict())
        elif args.command == "status":
            emit(plane.status(args.task_id).to_dict())
        elif args.command == "events":
            emit(plane.events(args.task_id))
        elif args.command == "observe":
            emit(
                plane.observe(
                    args.task_id,
                    outcome=AgentOutcome(args.outcome),
                    response=args.response,
                    error=args.error,
                ).to_dict()
            )
        elif args.command == "accept":
            emit(
                plane.accept(
                    args.task_id,
                    result=AcceptanceResult(args.result),
                    evidence=tuple(args.evidence),
                ).to_dict()
            )
        return 0
    except ControlPlaneError as exc:
        emit({"error": type(exc).__name__, "message": str(exc)})
        return 2


if __name__ == "__main__":
    sys.exit(main())
