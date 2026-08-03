from __future__ import annotations

import argparse

from .capability_cli import build_schedule
from .codex_cli import (
    codex_doctor_command,
    codex_manual_command,
    codex_resume_command,
    codex_run_command,
    codex_status_command,
)
from .common import emit, load_json
from .context import build_context
from .done import evaluate_done
from .environment import bootstrap, doctor, validate
from .learning import merge
from .orchestrator import create_plan
from .plugin_cli import (
    discover_plugins,
    inspect_plugin_package,
    validate_installed_plugin,
)
from .plugin_manager_cli import (
    install_plugin_command,
    list_plugins_command,
    plugin_status_command,
    remove_plugin_command,
    rollback_plugin_command,
    upgrade_plugin_command,
)
from .release import build_release
from .release_cli import (
    release_build_command,
    release_inspect_command,
    release_publish_command,
    release_tag_command,
    release_validate_command,
)
from .runtime_cli import run_manifest
from .vault import initialize_vault, vault_status
from .verifier import verify


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="empy",
        description="Govern AI-assisted product development from request to verified release.",
    )
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

    doctor_parser = sub.add_parser("doctor", help="Inspect the local development environment")
    doctor_parser.add_argument("--project-root", default=".")
    doctor_parser.add_argument("--vault")
    doctor_parser.add_argument("--output")

    bootstrap_parser = sub.add_parser(
        "bootstrap",
        help="Create a compatible virtual environment and install Empy Studio",
    )
    bootstrap_parser.add_argument("--project-root", default=".")
    bootstrap_parser.add_argument("--venv", default=".venv")
    bootstrap_parser.add_argument("--dev", action="store_true")
    bootstrap_parser.add_argument("--python")
    bootstrap_parser.add_argument("--dry-run", action="store_true")
    bootstrap_parser.add_argument("--output")

    validate_parser = sub.add_parser("validate", help="Run Ruff, MyPy, and Pytest before delivery")
    validate_parser.add_argument("--project-root", default=".")
    validate_parser.add_argument("--fix", action="store_true")
    validate_parser.add_argument("--output")

    done_parser = sub.add_parser("done", help="Evaluate the Definition of Done")
    done_parser.add_argument("--project-root", default=".")
    done_parser.add_argument("--output")

    release_parser = sub.add_parser(
        "release",
        help="Build and publish controlled releases",
    )
    release_sub = release_parser.add_subparsers(
        dest="release_command",
        required=True,
    )

    release_validate = release_sub.add_parser("validate")
    release_validate.add_argument("--manifest", required=True)
    release_validate.add_argument("--changelog", required=True)
    release_validate.add_argument("--output")

    release_build = release_sub.add_parser("build")
    release_build.add_argument("--manifest", required=True)
    release_build.add_argument("--source-root", required=True)
    release_build.add_argument(
        "--include",
        action="append",
        required=True,
    )
    release_build.add_argument("--changelog", required=True)
    release_build.add_argument("--output-dir", required=True)
    release_build.add_argument("--output")

    release_tag = release_sub.add_parser("tag")
    release_tag.add_argument("--manifest", required=True)
    release_tag.add_argument(
        "--repository-root",
        required=True,
    )
    release_tag.add_argument(
        "--expected-branch",
        default="main",
    )
    release_tag.add_argument("--push", action="store_true")
    release_tag.add_argument("--remote", default="origin")
    release_tag.add_argument("--output")

    release_publish = release_sub.add_parser("publish")
    release_publish.add_argument("--manifest", required=True)
    release_publish.add_argument(
        "--artifact-index",
        required=True,
    )
    release_publish.add_argument(
        "--release-notes",
        required=True,
    )
    release_publish.add_argument(
        "--repository-root",
        required=True,
    )
    release_publish.add_argument(
        "--repository",
        required=True,
    )
    release_publish.add_argument(
        "--token-env",
        default="GITHUB_TOKEN",
    )
    release_publish.add_argument(
        "--rollback-dir",
        required=True,
    )
    release_publish.add_argument(
        "--expected-branch",
        default="main",
    )
    release_publish.add_argument(
        "--workflow-name",
        default="CI",
    )
    release_publish.add_argument(
        "--target-commitish",
        default="main",
    )
    release_publish.add_argument(
        "--latest-strategy",
        choices=("auto", "always", "never", "legacy"),
        default="auto",
    )
    release_publish.add_argument(
        "--draft",
        action="store_true",
    )
    release_publish.add_argument("--output")

    release_inspect = release_sub.add_parser("inspect")
    release_inspect.add_argument("--manifest", required=True)
    release_inspect.add_argument(
        "--artifact-index",
        required=True,
    )
    release_inspect.add_argument("--output")


    runtime_parser = sub.add_parser("runtime", help="Execute a host-neutral multi-agent run")
    runtime_sub = runtime_parser.add_subparsers(dest="runtime_command", required=True)
    runtime_run = runtime_sub.add_parser("run", help="Run agents from a JSON manifest")
    runtime_run.add_argument("--manifest", required=True)
    runtime_run.add_argument("--output-root", required=True)
    runtime_run.add_argument("--output")


    capabilities_parser = sub.add_parser(
        "capabilities",
        help="Plan agent assignment from a capability graph",
    )
    capabilities_sub = capabilities_parser.add_subparsers(
        dest="capabilities_command",
        required=True,
    )
    capabilities_plan = capabilities_sub.add_parser(
        "plan",
        help="Score and select agents for manifest tasks",
    )
    capabilities_plan.add_argument("--manifest", required=True)
    capabilities_plan.add_argument("--output")

    plugin_parser = sub.add_parser(
        "plugin",
        help="Discover, inspect, and validate Empy Studio plugins",
    )
    plugin_sub = plugin_parser.add_subparsers(
        dest="plugin_command",
        required=True,
    )

    plugin_discover = plugin_sub.add_parser(
        "discover",
        help="Discover installed plugins without importing code",
    )
    plugin_discover.add_argument(
        "--root",
        action="append",
        required=True,
    )
    plugin_discover.add_argument(
        "--empy-version",
        required=True,
    )
    plugin_discover.add_argument("--output")

    plugin_inspect = plugin_sub.add_parser(
        "inspect",
        help="Verify and inspect an .empy-plugin artifact",
    )
    plugin_inspect.add_argument(
        "--package",
        required=True,
    )
    plugin_inspect.add_argument(
        "--empy-version",
        required=True,
    )
    plugin_inspect.add_argument("--output")

    plugin_validate = plugin_sub.add_parser(
        "validate",
        help="Validate an installed plugin directory",
    )
    plugin_validate.add_argument(
        "--plugin-root",
        required=True,
    )
    plugin_validate.add_argument(
        "--empy-version",
        required=True,
    )
    plugin_validate.add_argument("--output")

    plugin_install = plugin_sub.add_parser(
        "install",
        help="Install a verified plugin package",
    )
    plugin_install.add_argument("--source", required=True)
    plugin_install.add_argument("--store", required=True)
    plugin_install.add_argument("--empy-version", required=True)
    plugin_install.add_argument("--output")

    plugin_upgrade = plugin_sub.add_parser(
        "upgrade",
        help="Install and activate a newer plugin version",
    )
    plugin_upgrade.add_argument("--source", required=True)
    plugin_upgrade.add_argument("--store", required=True)
    plugin_upgrade.add_argument("--empy-version", required=True)
    plugin_upgrade.add_argument("--output")

    plugin_rollback = plugin_sub.add_parser(
        "rollback",
        help="Activate an already-installed plugin version",
    )
    plugin_rollback.add_argument("--plugin-id", required=True)
    plugin_rollback.add_argument("--version", required=True)
    plugin_rollback.add_argument("--store", required=True)
    plugin_rollback.add_argument("--output")

    plugin_remove = plugin_sub.add_parser(
        "remove",
        help="Remove a plugin or one installed version",
    )
    plugin_remove.add_argument("--plugin-id", required=True)
    plugin_remove.add_argument("--version")
    plugin_remove.add_argument("--replacement-version")
    plugin_remove.add_argument("--store", required=True)
    plugin_remove.add_argument("--output")

    plugin_list = plugin_sub.add_parser(
        "list",
        help="List installed plugins and versions",
    )
    plugin_list.add_argument("--store", required=True)
    plugin_list.add_argument("--output")

    plugin_status = plugin_sub.add_parser(
        "status",
        help="Inspect Plugin Store health",
    )
    plugin_status.add_argument("--store", required=True)
    plugin_status.add_argument("--output")

    codex_parser = sub.add_parser(
        "codex",
        help="Diagnose and run bounded Codex workflows",
    )
    codex_sub = codex_parser.add_subparsers(
        dest="codex_command",
        required=True,
    )

    codex_doctor = codex_sub.add_parser("doctor")
    codex_doctor.add_argument("--manifest", required=True)
    codex_doctor.add_argument("--codex-executable", default="codex")
    codex_doctor.add_argument("--output")

    codex_run = codex_sub.add_parser("run")
    codex_run.add_argument("--manifest", required=True)
    codex_run.add_argument("--codex-executable", default="codex")
    codex_run.add_argument("--no-manual-fallback", action="store_true")
    codex_run.add_argument("--output")

    codex_resume = codex_sub.add_parser("resume")
    codex_resume.add_argument("--manifest", required=True)
    codex_resume.add_argument("--prompt", required=True)
    codex_resume.add_argument("--codex-executable", default="codex")
    codex_resume.add_argument("--output")

    codex_manual = codex_sub.add_parser("manual")
    codex_manual.add_argument("--manifest", required=True)
    codex_manual.add_argument("--reason", required=True)
    codex_manual.add_argument("--output")

    codex_status = codex_sub.add_parser("status")
    codex_status.add_argument("--manifest", required=True)
    codex_status.add_argument("--output")

    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "plan":
        emit(create_plan(load_json(args.project), load_json(args.request)), args.output)
    elif args.command == "learn":
        emit(merge(load_json(args.graph), load_json(args.sprint)), args.output)
    elif args.command == "done":
        emit(evaluate_done(args.project_root), args.output)
    elif args.command == "release" and args.release_command == "build":
        emit(
            build_release(
                args.project_root,
                output_dir=args.output_dir,
                version=args.version,
                skip_done_check=args.skip_done_check,
            ),
            args.output,
        )
    elif args.command == "capabilities" and args.capabilities_command == "plan":
        emit(build_schedule(args.manifest), args.output)
    elif args.command == "runtime" and args.runtime_command == "run":
        emit(run_manifest(args.manifest, args.output_root), args.output)
    elif args.command == "plugin" and args.plugin_command == "discover":
        emit(
            discover_plugins(
                args.root,
                args.empy_version,
            ),
            args.output,
        )
    elif args.command == "plugin" and args.plugin_command == "inspect":
        emit(
            inspect_plugin_package(
                args.package,
                args.empy_version,
            ),
            args.output,
        )
    elif args.command == "plugin" and args.plugin_command == "validate":
        emit(
            validate_installed_plugin(
                args.plugin_root,
                args.empy_version,
            ),
            args.output,
        )
    elif args.command == "plugin" and args.plugin_command == "install":
        emit(
            install_plugin_command(
                args.source,
                args.store,
                args.empy_version,
            ),
            args.output,
        )
    elif args.command == "plugin" and args.plugin_command == "upgrade":
        emit(
            upgrade_plugin_command(
                args.source,
                args.store,
                args.empy_version,
            ),
            args.output,
        )
    elif args.command == "plugin" and args.plugin_command == "rollback":
        emit(
            rollback_plugin_command(
                args.plugin_id,
                args.version,
                args.store,
            ),
            args.output,
        )
    elif args.command == "plugin" and args.plugin_command == "remove":
        emit(
            remove_plugin_command(
                args.plugin_id,
                args.store,
                version=args.version,
                replacement_version=args.replacement_version,
            ),
            args.output,
        )
    elif args.command == "plugin" and args.plugin_command == "list":
        emit(
            list_plugins_command(args.store),
            args.output,
        )
    elif args.command == "plugin" and args.plugin_command == "status":
        emit(
            plugin_status_command(args.store),
            args.output,
        )
    elif args.command == "codex" and args.codex_command == "doctor":
        emit(
            codex_doctor_command(
                args.manifest,
                args.codex_executable,
            ),
            args.output,
        )
    elif args.command == "codex" and args.codex_command == "run":
        emit(
            codex_run_command(
                args.manifest,
                args.codex_executable,
                args.no_manual_fallback,
            ),
            args.output,
        )
    elif args.command == "codex" and args.codex_command == "resume":
        emit(
            codex_resume_command(
                args.manifest,
                args.prompt,
                args.codex_executable,
            ),
            args.output,
        )
    elif args.command == "codex" and args.codex_command == "manual":
        emit(
            codex_manual_command(
                args.manifest,
                args.reason,
            ),
            args.output,
        )
    elif args.command == "codex" and args.codex_command == "status":
        emit(
            codex_status_command(args.manifest),
            args.output,
        )
    elif args.command == "release" and args.release_command == "validate":
        emit(
            release_validate_command(
                args.manifest,
                args.changelog,
            ),
            args.output,
        )
    elif args.command == "release" and args.release_command == "build":
        emit(
            release_build_command(
                args.manifest,
                args.source_root,
                args.include,
                args.changelog,
                args.output_dir,
            ),
            args.output,
        )
    elif args.command == "release" and args.release_command == "tag":
        emit(
            release_tag_command(
                args.manifest,
                args.repository_root,
                args.expected_branch,
                args.push,
                args.remote,
            ),
            args.output,
        )
    elif args.command == "release" and args.release_command == "publish":
        emit(
            release_publish_command(
                args.manifest,
                args.artifact_index,
                args.release_notes,
                args.repository_root,
                args.repository,
                args.token_env,
                args.rollback_dir,
                args.expected_branch,
                args.workflow_name,
                args.target_commitish,
                args.latest_strategy,
                args.draft,
            ),
            args.output,
        )
    elif args.command == "release" and args.release_command == "inspect":
        emit(
            release_inspect_command(
                args.manifest,
                args.artifact_index,
            ),
            args.output,
        )
    elif args.command == "verify":
        emit(verify(load_json(args.manifest)), args.output)
    elif args.command == "doctor":
        emit(doctor(args.project_root, args.vault), args.output)
    elif args.command == "bootstrap":
        emit(
            bootstrap(
                project_root=args.project_root,
                venv_dir=args.venv,
                include_dev=args.dev,
                python_executable=args.python,
                dry_run=args.dry_run,
            ),
            args.output,
        )
    elif args.command == "validate":
        emit(validate(args.project_root, args.fix), args.output)
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
