"""Materialize Empy Studio's independent sample project."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from importlib.resources import as_file, files
from pathlib import Path


@contextmanager
def _sample_source() -> Iterator[Path]:
    """Yield the packaged sample, with a source-checkout fallback."""

    packaged = files("empy_studio").joinpath("sample_project")
    if packaged.is_dir():
        with as_file(packaged) as path:
            yield path
        return

    checkout = Path(__file__).resolve().parents[2] / "examples" / "fixtures" / "php-site"
    if not checkout.is_dir():
        raise FileNotFoundError("Empy Studio sample project is not available")
    yield checkout


def copy_sample_project(destination: str | Path) -> dict[str, str]:
    """Copy the independent sample to a new directory without overwriting it."""

    target = Path(destination).expanduser().resolve()
    if target.exists():
        raise FileExistsError(
            f"Refusing to overwrite existing sample destination: {target}"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    with _sample_source() as source:
        shutil.copytree(source, target)
    return {
        "status": "copied",
        "project_type": "php",
        "path": str(target),
        "next_step": "Open this folder in Empy Studio and submit a ticket.",
    }
