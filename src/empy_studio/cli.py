from __future__ import annotations

import argparse
from pathlib import Path

from .common import emit, load_json
from .learning import merge
from .orchestrator import create_plan
from .verifier import verify


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="empy", description="Govern AI-assisted product development from request to verified release.")
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="Create a bounded multi-agent task graph")
    plan.add_argument("--project", required=True)
    plan.add_argument("--request", required=True)
    plan.add_argument("--output")

    learn = sub.add_parser("learn", help="Merge evidence-backed Sprint lessons")
    learn.add_argument("--graph", required=True)
    learn.add_argument("--sprint", required=True)
    learn.add_argument("--output")

    verify_parser = sub.add_parser("verify", help="Run local checks and preserve external checks as pending")
    verify_parser.add_argument("--manifest", required=True)
    verify_parser.add_argument("--output")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "plan":
        emit(create_plan(load_json(args.project), load_json(args.request)), args.output)
    elif args.command == "learn":
        emit(merge(load_json(args.graph), load_json(args.sprint)), args.output)
    else:
        emit(verify(load_json(args.manifest)), args.output)


if __name__ == "__main__":
    main()
