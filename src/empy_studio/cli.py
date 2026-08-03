from __future__ import annotations

import argparse

from .common import emit, load_json
from .context import build_context
from .learning import merge
from .orchestrator import create_plan
from .vault import initialize_vault, vault_status
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

    vault = sub.add_parser("vault", help="Create and inspect a persistent Project Vault")
    vault_sub = vault.add_subparsers(dest="vault_command", required=True)

    vault_init = vault_sub.add_parser("init", help="Create a Project Vault and baseline snapshot")
    vault_init.add_argument("--project-root", required=True)
    vault_init.add_argument("--vault", required=True)
    vault_init.add_argument("--project-id", required=True)
    vault_init.add_argument("--name", required=True)
    vault_init.add_argument("--no-snapshot", action="store_true")
    vault_init.add_argument("--force", action="store_true")
    vault_init.add_argument("--output")

    vault_status_parser = vault_sub.add_parser("status", help="Inspect a Project Vault")
    vault_status_parser.add_argument("--vault", required=True)
    vault_status_parser.add_argument("--output")

    context = sub.add_parser("context", help="Build a small, task-specific agent context package")
    context_sub = context.add_subparsers(dest="context_command", required=True)
    context_build = context_sub.add_parser("build", help="Select relevant files from a Project Vault")
    context_build.add_argument("--vault", required=True)
    context_build.add_argument("--request", required=True)
    context_build.add_argument("--output-dir", required=True)
    context_build.add_argument("--max-bytes", type=int, default=64000)
    context_build.add_argument("--include", action="append", default=[])
    context_build.add_argument("--output")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "plan":
        emit(create_plan(load_json(args.project), load_json(args.request)), args.output)
    elif args.command == "learn":
        emit(merge(load_json(args.graph), load_json(args.sprint)), args.output)
    elif args.command == "verify":
        emit(verify(load_json(args.manifest)), args.output)
    elif args.command == "vault" and args.vault_command == "init":
        emit(
            initialize_vault(
                project_root=args.project_root,
                vault_root=args.vault,
                project_id=args.project_id,
                project_name=args.name,
                snapshot=not args.no_snapshot,
                force=args.force,
            ),
            args.output,
        )
    elif args.command == "vault":
        emit(vault_status(args.vault), args.output)
    else:
        emit(
            build_context(
                vault_root=args.vault,
                request_path=args.request,
                output_dir=args.output_dir,
                max_bytes=args.max_bytes,
                explicit_files=args.include,
            ),
            args.output,
        )


if __name__ == "__main__":
    main()
