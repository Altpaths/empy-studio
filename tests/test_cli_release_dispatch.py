from __future__ import annotations

import sys

from empy_studio import cli


def test_release_build_dispatches_to_manifest_builder(
    monkeypatch,
) -> None:
    calls: list[tuple[str, str, list[str], str, str]] = []

    def fake_build(
        manifest: str,
        source_root: str,
        include: list[str],
        changelog: str,
        output_dir: str,
    ) -> dict[str, str]:
        calls.append(
            (manifest, source_root, include, changelog, output_dir)
        )
        return {"status": "built"}

    emitted: list[dict[str, str]] = []
    monkeypatch.setattr(cli, "release_build_command", fake_build)
    monkeypatch.setattr(
        cli,
        "emit",
        lambda value, output=None: emitted.append(value),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "empy",
            "release",
            "build",
            "--manifest",
            "release-manifest.json",
            "--source-root",
            ".",
            "--include",
            "src",
            "--include",
            "README.md",
            "--changelog",
            "CHANGELOG.md",
            "--output-dir",
            "dist",
        ],
    )

    cli.main()

    assert calls == [
        (
            "release-manifest.json",
            ".",
            ["src", "README.md"],
            "CHANGELOG.md",
            "dist",
        )
    ]
    assert emitted == [{"status": "built"}]
