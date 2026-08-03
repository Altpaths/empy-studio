from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .plugin_package import PACKAGE_SUFFIX

DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_BYTES = 100 * 1024 * 1024
USER_AGENT = "Empy-Studio-Plugin-Package-Manager/1"


@dataclass(frozen=True)
class ResolvedPluginSource:
    source: str
    source_type: str
    local_path: str
    filename: str
    sha256: str
    size_bytes: int
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_filename(value: str) -> str:
    name = Path(urllib.parse.unquote(value)).name
    safe = "".join(
        char
        if char.isalnum() or char in "._-"
        else "_"
        for char in name
    )
    if not safe:
        raise ValueError("Unable to derive a safe plugin filename")
    if not safe.endswith(PACKAGE_SUFFIX):
        raise ValueError(
            f"Resolved plugin source must use the {PACKAGE_SUFFIX} suffix"
        )
    return safe


def _validate_size(size_bytes: int, max_bytes: int) -> None:
    if size_bytes < 0:
        raise ValueError("Source size cannot be negative")
    if size_bytes > max_bytes:
        raise ValueError(
            f"Plugin package exceeds maximum size of {max_bytes} bytes"
        )


def _copy_local_source(
    source_path: Path,
    destination_dir: Path,
    *,
    max_bytes: int,
) -> ResolvedPluginSource:
    path = source_path.expanduser().resolve()

    if not path.is_file():
        raise FileNotFoundError(path)

    filename = _safe_filename(path.name)
    size_bytes = path.stat().st_size
    _validate_size(size_bytes, max_bytes)

    destination = destination_dir / filename
    shutil.copy2(path, destination)

    return ResolvedPluginSource(
        source=str(path),
        source_type="local_file",
        local_path=str(destination),
        filename=filename,
        sha256=_sha256_file(destination),
        size_bytes=size_bytes,
        metadata={},
    )


def _download_http_source(
    url: str,
    destination_dir: Path,
    *,
    timeout_seconds: float,
    max_bytes: int,
    source_type: str = "http",
    metadata: dict[str, Any] | None = None,
) -> ResolvedPluginSource:
    destination_dir.mkdir(parents=True, exist_ok=True)

    parsed = urllib.parse.urlparse(url)

    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only HTTP and HTTPS plugin sources are supported")

    filename = _safe_filename(parsed.path)
    destination = destination_dir / filename

    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT},
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=timeout_seconds,
        ) as response:
            content_length = response.headers.get("Content-Length")
            if content_length is not None:
                _validate_size(int(content_length), max_bytes)

            digest = hashlib.sha256()
            size_bytes = 0

            with destination.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break

                    size_bytes += len(chunk)
                    _validate_size(size_bytes, max_bytes)

                    digest.update(chunk)
                    handle.write(chunk)

    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"Plugin download failed with HTTP {exc.code}: {url}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Plugin download failed: {url}: {exc.reason}"
        ) from exc

    return ResolvedPluginSource(
        source=url,
        source_type=source_type,
        local_path=str(destination),
        filename=filename,
        sha256=digest.hexdigest(),
        size_bytes=size_bytes,
        metadata=metadata or {},
    )


def resolve_github_release_asset(
    repository: str,
    asset_name: str,
    destination_dir: str | Path,
    *,
    tag: str = "latest",
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> ResolvedPluginSource:
    if repository.count("/") != 1:
        raise ValueError(
            "GitHub repository must use the 'owner/repository' format"
        )

    if tag == "latest":
        api_url = (
            f"https://api.github.com/repos/{repository}/releases/latest"
        )
    else:
        encoded_tag = urllib.parse.quote(tag, safe="")
        api_url = (
            f"https://api.github.com/repos/{repository}/releases/tags/"
            f"{encoded_tag}"
        )

    request = urllib.request.Request(
        api_url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=timeout_seconds,
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"GitHub release lookup failed with HTTP {exc.code}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"GitHub release lookup failed: {exc.reason}"
        ) from exc

    if not isinstance(payload, dict):
        raise TypeError("GitHub release response must be a JSON object")

    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise TypeError("GitHub release assets must be a list")

    matching = [
        asset
        for asset in assets
        if isinstance(asset, dict)
        and asset.get("name") == asset_name
    ]

    if not matching:
        raise FileNotFoundError(
            f"GitHub release asset not found: {asset_name}"
        )
    if len(matching) > 1:
        raise ValueError(
            f"GitHub release contains duplicate asset names: {asset_name}"
        )

    asset = matching[0]
    download_url = asset.get("browser_download_url")
    if not isinstance(download_url, str):
        raise TypeError(
            "GitHub release asset is missing browser_download_url"
        )

    metadata = {
        "repository": repository,
        "requested_tag": tag,
        "release_tag": payload.get("tag_name"),
        "release_id": payload.get("id"),
        "asset_id": asset.get("id"),
        "asset_name": asset_name,
    }

    return _download_http_source(
        download_url,
        Path(destination_dir),
        timeout_seconds=timeout_seconds,
        max_bytes=max_bytes,
        source_type="github_release",
        metadata=metadata,
    )


def resolve_plugin_source(
    source: str,
    destination_dir: str | Path,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> ResolvedPluginSource:
    destination = Path(destination_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)

    parsed = urllib.parse.urlparse(source)

    if parsed.scheme in {"http", "https"}:
        return _download_http_source(
            source,
            destination,
            timeout_seconds=timeout_seconds,
            max_bytes=max_bytes,
        )

    if parsed.scheme == "file":
        local_path = Path(
            urllib.request.url2pathname(parsed.path)
        )
        return _copy_local_source(
            local_path,
            destination,
            max_bytes=max_bytes,
        )

    if parsed.scheme:
        raise ValueError(
            f"Unsupported plugin source scheme: {parsed.scheme}"
        )

    return _copy_local_source(
        Path(source),
        destination,
        max_bytes=max_bytes,
    )


def resolve_to_temporary_directory(
    source: str,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> tuple[tempfile.TemporaryDirectory[str], ResolvedPluginSource]:
    temporary = tempfile.TemporaryDirectory(
        prefix="empy-plugin-source-"
    )
    try:
        resolved = resolve_plugin_source(
            source,
            temporary.name,
            timeout_seconds=timeout_seconds,
            max_bytes=max_bytes,
        )
    except Exception:
        temporary.cleanup()
        raise

    return temporary, resolved
