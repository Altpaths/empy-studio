from __future__ import annotations

import io
import json
import urllib.error
from email.message import Message
from pathlib import Path
from typing import Any

try:
    from typing import Self
except ImportError:  # Python 3.10
    from typing_extensions import Self

import pytest

from empy_studio.plugin_source import (
    resolve_github_release_asset,
    resolve_plugin_source,
)


class FakeResponse:
    def __init__(
        self,
        body: bytes,
        *,
        content_length: int | None = None,
    ) -> None:
        self._stream = io.BytesIO(body)
        self.headers = Message()
        if content_length is not None:
            self.headers["Content-Length"] = str(content_length)

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: object,
        exc: object,
        traceback: object,
    ) -> None:
        return None


def test_resolves_local_plugin_source(
    tmp_path: Path,
) -> None:
    package = tmp_path / "example.empy-plugin"
    package.write_bytes(b"plugin-package")

    resolved = resolve_plugin_source(
        str(package),
        tmp_path / "cache",
    )

    assert resolved.source_type == "local_file"
    assert resolved.filename == "example.empy-plugin"
    assert resolved.size_bytes == len(b"plugin-package")
    assert Path(resolved.local_path).read_bytes() == b"plugin-package"
    assert len(resolved.sha256) == 64


def test_resolves_file_url(
    tmp_path: Path,
) -> None:
    package = tmp_path / "example.empy-plugin"
    package.write_bytes(b"plugin-package")

    resolved = resolve_plugin_source(
        package.as_uri(),
        tmp_path / "cache",
    )

    assert resolved.source_type == "local_file"
    assert Path(resolved.local_path).is_file()


def test_rejects_invalid_package_suffix(
    tmp_path: Path,
) -> None:
    source = tmp_path / "example.zip"
    source.write_bytes(b"invalid")

    with pytest.raises(
        ValueError,
        match=".empy-plugin",
    ):
        resolve_plugin_source(
            str(source),
            tmp_path / "cache",
        )


def test_rejects_local_source_over_size_limit(
    tmp_path: Path,
) -> None:
    package = tmp_path / "large.empy-plugin"
    package.write_bytes(b"x" * 20)

    with pytest.raises(
        ValueError,
        match="maximum size",
    ):
        resolve_plugin_source(
            str(package),
            tmp_path / "cache",
            max_bytes=10,
        )


def test_downloads_http_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = b"downloaded-package"

    def fake_urlopen(
        request: Any,
        timeout: float,
    ) -> FakeResponse:
        assert timeout == 5.0
        return FakeResponse(
            body,
            content_length=len(body),
        )

    monkeypatch.setattr(
        "urllib.request.urlopen",
        fake_urlopen,
    )

    resolved = resolve_plugin_source(
        "https://example.com/example.empy-plugin",
        tmp_path / "cache",
        timeout_seconds=5.0,
    )

    assert resolved.source_type == "http"
    assert Path(resolved.local_path).read_bytes() == body


def test_stops_http_download_over_size_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(
        request: Any,
        timeout: float,
    ) -> FakeResponse:
        return FakeResponse(
            b"x" * 20,
            content_length=20,
        )

    monkeypatch.setattr(
        "urllib.request.urlopen",
        fake_urlopen,
    )

    with pytest.raises(
        ValueError,
        match="maximum size",
    ):
        resolve_plugin_source(
            "https://example.com/large.empy-plugin",
            tmp_path / "cache",
            max_bytes=10,
        )


def test_resolves_github_release_asset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release_payload = {
        "id": 101,
        "tag_name": "v1.2.0",
        "assets": [
            {
                "id": 202,
                "name": "example.empy-plugin",
                "browser_download_url": (
                    "https://github.com/example/download/"
                    "example.empy-plugin"
                ),
            }
        ],
    }
    package_body = b"github-package"
    calls: list[str] = []

    def fake_urlopen(
        request: Any,
        timeout: float,
    ) -> FakeResponse:
        url = request.full_url
        calls.append(url)

        if "api.github.com" in url:
            return FakeResponse(
                json.dumps(release_payload).encode("utf-8")
            )

        return FakeResponse(
            package_body,
            content_length=len(package_body),
        )

    monkeypatch.setattr(
        "urllib.request.urlopen",
        fake_urlopen,
    )

    resolved = resolve_github_release_asset(
        "owner/repository",
        "example.empy-plugin",
        tmp_path / "cache",
    )

    assert resolved.source_type == "github_release"
    assert resolved.metadata["release_tag"] == "v1.2.0"
    assert resolved.metadata["asset_id"] == 202
    assert len(calls) == 2


def test_reports_missing_github_asset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release_payload = {
        "id": 101,
        "tag_name": "v1.2.0",
        "assets": [],
    }

    def fake_urlopen(
        request: Any,
        timeout: float,
    ) -> FakeResponse:
        return FakeResponse(
            json.dumps(release_payload).encode("utf-8")
        )

    monkeypatch.setattr(
        "urllib.request.urlopen",
        fake_urlopen,
    )

    with pytest.raises(
        FileNotFoundError,
        match="asset not found",
    ):
        resolve_github_release_asset(
            "owner/repository",
            "missing.empy-plugin",
            tmp_path / "cache",
        )


def test_wraps_http_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(
        request: Any,
        timeout: float,
    ) -> FakeResponse:
        raise urllib.error.HTTPError(
            request.full_url,
            404,
            "Not Found",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr(
        "urllib.request.urlopen",
        fake_urlopen,
    )

    with pytest.raises(
        RuntimeError,
        match="HTTP 404",
    ):
        resolve_plugin_source(
            "https://example.com/missing.empy-plugin",
            tmp_path / "cache",
        )
