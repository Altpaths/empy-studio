from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .plugin_manifest import PluginManifest


@dataclass(frozen=True)
class LoadedPlugin:
    root: str
    module_name: str
    manifest: PluginManifest
    instance: Any


def _resolve_entrypoint_module(
    plugin_root: Path,
    module_name: str,
) -> tuple[Path, bool]:
    payload_root = plugin_root / "payload"

    module_path = payload_root.joinpath(
        *module_name.split(".")
    ).with_suffix(".py")
    if module_path.is_file():
        return module_path, False

    package_init = (
        payload_root.joinpath(*module_name.split("."))
        / "__init__.py"
    )
    if package_init.is_file():
        return package_init, True

    raise ImportError(
        f"Entrypoint module not found in plugin payload: {module_name}"
    )


def _isolated_module_name(manifest: PluginManifest) -> str:
    safe_plugin_id = manifest.plugin_id.replace("-", "_")
    safe_version = (
        manifest.version.replace(".", "_")
        .replace("-", "_")
        .replace("+", "_")
    )
    return f"_empy_plugin_{safe_plugin_id}_{safe_version}"


def load_installed_plugin(
    plugin_root: str | Path,
    *,
    empy_version: str,
) -> LoadedPlugin:
    root = Path(plugin_root).expanduser().resolve()

    if not root.is_dir():
        raise FileNotFoundError(root)

    manifest_path = root / "plugin.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)

    raw_manifest = json.loads(
        manifest_path.read_text(encoding="utf-8")
    )
    if not isinstance(raw_manifest, dict):
        raise TypeError("plugin.json must contain a JSON object")

    manifest = PluginManifest.from_dict(raw_manifest)
    if not manifest.supports(empy_version):
        raise ValueError(
            f"Plugin {manifest.plugin_id} requires Empy Studio "
            f"{manifest.empy_requires}; current version is {empy_version}"
        )

    entrypoint_module, entrypoint_object = (
        manifest.entrypoint.split(":", 1)
    )

    module_path, is_package = _resolve_entrypoint_module(
        root,
        entrypoint_module,
    )

    isolated_name = _isolated_module_name(manifest)

    spec_kwargs: dict[str, Any] = {}
    if is_package:
        spec_kwargs["submodule_search_locations"] = [
            str(module_path.parent)
        ]

    spec = importlib.util.spec_from_file_location(
        isolated_name,
        module_path,
        **spec_kwargs,
    )
    if spec is None or spec.loader is None:
        raise ImportError(
            f"Unable to create import specification for {module_path}"
        )

    module = importlib.util.module_from_spec(spec)
    previous_module = sys.modules.get(isolated_name)
    sys.modules[isolated_name] = module

    try:
        spec.loader.exec_module(module)

        try:
            plugin_object = getattr(
                module,
                entrypoint_object,
            )
        except AttributeError as exc:
            raise ImportError(
                f"Plugin entrypoint object not found: "
                f"{entrypoint_object}"
            ) from exc

        instance = (
            plugin_object()
            if isinstance(plugin_object, type)
            else plugin_object
        )

    except Exception:
        if previous_module is None:
            sys.modules.pop(isolated_name, None)
        else:
            sys.modules[isolated_name] = previous_module
        raise

    return LoadedPlugin(
        root=str(root),
        module_name=isolated_name,
        manifest=manifest,
        instance=instance,
    )
