from __future__ import annotations

from empy_studio.cli import build_parser


def test_codex_doctor_parser() -> None:
    args = build_parser().parse_args(
        ["codex", "doctor", "--manifest", "manifest.json"]
    )
    assert args.codex_command == "doctor"


def test_codex_run_parser() -> None:
    args = build_parser().parse_args(
        [
            "codex",
            "run",
            "--manifest",
            "manifest.json",
            "--no-manual-fallback",
        ]
    )
    assert args.no_manual_fallback is True


def test_codex_resume_parser() -> None:
    args = build_parser().parse_args(
        [
            "codex",
            "resume",
            "--manifest",
            "manifest.json",
            "--prompt",
            "Continue",
        ]
    )
    assert args.prompt == "Continue"


def test_codex_manual_parser() -> None:
    args = build_parser().parse_args(
        [
            "codex",
            "manual",
            "--manifest",
            "manifest.json",
            "--reason",
            "Unavailable",
        ]
    )
    assert args.codex_command == "manual"


def test_codex_status_parser() -> None:
    args = build_parser().parse_args(
        ["codex", "status", "--manifest", "manifest.json"]
    )
    assert args.codex_command == "status"
