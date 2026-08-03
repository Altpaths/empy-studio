from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .plugin_manifest import PluginManifest


@dataclass(frozen=True)
class DiscoveredPlugin:
    root: str
    manifest_path: str
    manifest: PluginManifest

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "manifest_path": self.manifest_path,
            "manifest": self.manifest.to_dict(),
        }


@dataclass(frozen=True)
class DiscoveryIssue:
    path: str
    error_type: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "path": self.path,
            "error_type": self.error_type,
            "message": self.message,
        }


def _read_manifest(path: Path) -> PluginManifest:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("plugin.json must contain a JSON object")
    return PluginManifest.from_dict(value)


def discover_installed_plugins(
    roots: list[str | Path],
    *,
    empy_version: str,
) -> dict[str, Any]:
    plugins: list[DiscoveredPlugin] = []
    issues: list[DiscoveryIssue] = []
    seen_plugin_ids: dict[str, str] = {}

    for raw_root in roots:
        root = Path(raw_root).expanduser()

        if not root.exists():
            issues.append(
                DiscoveryIssue(
                    path=str(root),
                    error_type="missing_root",
                    message="Plugin discovery root does not exist",
                )
            )
            continue

        if not root.is_dir():
            issues.append(
                DiscoveryIssue(
                    path=str(root),
                    error_type="invalid_root",
                    message="Plugin discovery root is not a directory",
                )
            )
            continue

        for candidate in sorted(root.iterdir(), key=lambda item: item.name):
            if not candidate.is_dir():
                continue

            manifest_path = candidate / "plugin.json"
            if not manifest_path.is_file():
                continue

            try:
                manifest = _read_manifest(manifest_path)

                if not manifest.supports(empy_version):
                    raise ValueError(
                        f"Plugin requires Empy Studio "
                        f"{manifest.empy_requires}; current version is "
                        f"{empy_version}"
                    )

                previous = seen_plugin_ids.get(manifest.plugin_id)
                if previous is not None:
                    raise ValueError(
                        f"Duplicate plugin_id {manifest.plugin_id!r}; "
                        f"already discovered at {previous}"
                    )

                seen_plugin_ids[manifest.plugin_id] = str(
                    candidate.resolve()
                )
                plugins.append(
                    DiscoveredPlugin(
                        root=str(candidate.resolve()),
                        manifest_path=str(manifest_path.resolve()),
                        manifest=manifest,
                    )
                )

            except json.JSONDecodeError as exc:
                issues.append(
                    DiscoveryIssue(
                        path=str(manifest_path),
                        error_type="invalid_json",
                        message=str(exc),
                    )
                )
            except KeyError as exc:
                issues.append(
                    DiscoveryIssue(
                        path=str(manifest_path),
                        error_type="missing_field",
                        message=str(exc),
                    )
                )
            except TypeError as exc:
                issues.append(
                    DiscoveryIssue(
                        path=str(manifest_path),
                        error_type="invalid_type",
                        message=str(exc),
                    )
                )
            except ValueError as exc:
                issues.append(
                    DiscoveryIssue(
                        path=str(manifest_path),
                        error_type="invalid_manifest",
                        message=str(exc),
                    )
                )

    plugins.sort(key=lambda item: item.manifest.plugin_id)
    issues.sort(key=lambda item: (item.path, item.error_type))

    return {
        "status": "ok" if not issues else "partial",
        "plugin_count": len(plugins),
        "issue_count": len(issues),
        "plugins": [plugin.to_dict() for plugin in plugins],
        "issues": [issue.to_dict() for issue in issues],
    }
