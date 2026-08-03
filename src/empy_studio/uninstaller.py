from __future__ import annotations

import hashlib
import json
import os
import shlex
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

UninstallerKind = Literal["shell", "powershell"]


@dataclass(frozen=True)
class InstallState:
    schema_version: int
    product: str
    version: str
    target: str
    package_sha256: str
    version_root: str
    wrapper_path: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InstallState:
        state = cls(
            schema_version=int(data["schema_version"]),
            product=str(data["product"]),
            version=str(data["version"]),
            target=str(data["target"]),
            package_sha256=str(data["package_sha256"]),
            version_root=str(data["version_root"]),
            wrapper_path=str(data["wrapper_path"]),
        )
        state.validate()
        return state

    @classmethod
    def load(cls, source: str | Path) -> InstallState:
        path = Path(source).expanduser().resolve()
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise TypeError("Install state must contain a JSON object")
        return cls.from_dict(value)

    def validate(self) -> None:
        if self.schema_version != 1:
            raise ValueError("Unsupported install-state schema version")
        if not self.product.strip():
            raise ValueError("Install-state product cannot be empty")
        if not self.version.strip():
            raise ValueError("Install-state version cannot be empty")
        if not self.target.strip():
            raise ValueError("Install-state target cannot be empty")
        if len(self.package_sha256) != 64 or any(
            character not in "0123456789abcdef"
            for character in self.package_sha256.lower()
        ):
            raise ValueError(
                "Install-state package_sha256 must be a "
                "64-character hexadecimal digest"
            )
        if not self.version_root.strip():
            raise ValueError("Install-state version_root cannot be empty")
        if not self.wrapper_path.strip():
            raise ValueError("Install-state wrapper_path cannot be empty")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class UninstallerSpec:
    product: str
    kind: UninstallerKind
    install_root: str
    state_filename: str = "install-state.json"
    current_filename: str = "current.json"
    unix_current_name: str = "current"

    def validate(self) -> None:
        if not self.product.strip():
            raise ValueError("Uninstaller product cannot be empty")
        if self.kind not in {"shell", "powershell"}:
            raise ValueError(f"Unsupported uninstaller kind: {self.kind}")
        if not self.install_root.strip():
            raise ValueError("Uninstaller install_root cannot be empty")
        for filename in (
            self.state_filename,
            self.current_filename,
            self.unix_current_name,
        ):
            if Path(filename).name != filename:
                raise ValueError(
                    "Uninstaller state names must not contain paths"
                )


@dataclass(frozen=True)
class UninstallerArtifact:
    kind: UninstallerKind
    path: str
    sha256: str
    size_bytes: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _shell(value: str) -> str:
    return shlex.quote(value)


def render_unix_uninstaller(spec: UninstallerSpec) -> str:
    spec.validate()
    if spec.kind != "shell":
        raise ValueError("Unix uninstaller requires shell kind")

    return f'''#!/bin/sh
set -eu

PRODUCT={_shell(spec.product)}
INSTALL_ROOT={_shell(spec.install_root)}
STATE_FILENAME={_shell(spec.state_filename)}
CURRENT_NAME={_shell(spec.unix_current_name)}

expand_home() {{
    case "$1" in
        '${{HOME}}'/*)
            printf '%s/%s\\n' "$HOME" "${{1#'${{HOME}}'/}}"
            ;;
        *)
            printf '%s\\n' "$1"
            ;;
    esac
}}

INSTALL_ROOT="$(expand_home "$INSTALL_ROOT")"
STATE_FILE="$INSTALL_ROOT/$STATE_FILENAME"

fail() {{
    printf 'ERROR: %s\\n' "$1" >&2
    exit 1
}}

[ -f "$STATE_FILE" ] || fail "Install state was not found: $STATE_FILE"

python_command=""
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        python_command="$candidate"
        break
    fi
done
[ -n "$python_command" ] || fail "Python is required to validate install state"

state_values="$(
    "$python_command" - "$STATE_FILE" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1]).resolve()
data = json.loads(path.read_text(encoding="utf-8"))
required = (
    "schema_version",
    "product",
    "version",
    "target",
    "package_sha256",
    "version_root",
    "wrapper_path",
)
missing = [key for key in required if key not in data]
if missing:
    raise SystemExit("Install state is missing: " + ", ".join(missing))
if data["schema_version"] != 1:
    raise SystemExit("Unsupported install-state schema")
for key in ("version_root", "wrapper_path"):
    value = pathlib.Path(data[key]).expanduser().resolve()
    print(f"{{key}}={{value}}")
PY
)"

version_root=""
wrapper_path=""

while IFS='=' read -r key value; do
    case "$key" in
        version_root) version_root="$value" ;;
        wrapper_path) wrapper_path="$value" ;;
    esac
done <<EOF
$state_values
EOF

[ -n "$version_root" ] || fail "Install state has no version_root"
[ -n "$wrapper_path" ] || fail "Install state has no wrapper_path"

case "$version_root" in
    "$INSTALL_ROOT"/versions/*) ;;
    *) fail "Refusing to remove path outside install root" ;;
esac

if [ -e "$wrapper_path" ] || [ -L "$wrapper_path" ]; then
    rm -f "$wrapper_path"
fi

if [ -e "$INSTALL_ROOT/$CURRENT_NAME" ] || [ -L "$INSTALL_ROOT/$CURRENT_NAME" ]; then
    rm -f "$INSTALL_ROOT/$CURRENT_NAME"
fi

if [ -d "$version_root" ]; then
    rm -rf "$version_root"
fi

rm -f "$STATE_FILE"

versions_root="$INSTALL_ROOT/versions"
if [ -d "$versions_root" ] && [ -z "$(find "$versions_root" -mindepth 1 -maxdepth 1 -print -quit)" ]; then
    rmdir "$versions_root"
fi

if [ -d "$INSTALL_ROOT" ] && [ -z "$(find "$INSTALL_ROOT" -mindepth 1 -maxdepth 1 -print -quit)" ]; then
    rmdir "$INSTALL_ROOT"
fi

printf '%s uninstalled successfully.\\n' "$PRODUCT"
'''


def render_windows_uninstaller(spec: UninstallerSpec) -> str:
    spec.validate()
    if spec.kind != "powershell":
        raise ValueError("Windows uninstaller requires powershell kind")

    product = "'" + spec.product.replace("'", "''") + "'"
    install_root = "'" + spec.install_root.replace("'", "''") + "'"
    state_filename = "'" + spec.state_filename.replace("'", "''") + "'"
    current_filename = "'" + spec.current_filename.replace("'", "''") + "'"

    return f'''#requires -Version 5.1
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Product = {product}
$InstallRoot = {install_root}
$StateFilename = {state_filename}
$CurrentFilename = {current_filename}

$InstallRoot = $ExecutionContext.InvokeCommand.ExpandString($InstallRoot)
$StateFile = Join-Path $InstallRoot $StateFilename
$CurrentFile = Join-Path $InstallRoot $CurrentFilename

if (-not (Test-Path -LiteralPath $StateFile -PathType Leaf)) {{
    throw "Install state was not found: $StateFile"
}}

$state = Get-Content -LiteralPath $StateFile -Raw | ConvertFrom-Json
$required = @(
    "schema_version",
    "product",
    "version",
    "target",
    "package_sha256",
    "version_root",
    "wrapper_path"
)

foreach ($name in $required) {{
    if ($null -eq $state.$name) {{
        throw "Install state is missing: $name"
    }}
}}

if ([int]$state.schema_version -ne 1) {{
    throw "Unsupported install-state schema"
}}

$resolvedInstallRoot = ([IO.Path]::GetFullPath($InstallRoot)).TrimEnd("\\")
$resolvedVersionRoot = [IO.Path]::GetFullPath([string]$state.version_root)
$versionsPrefix = (Join-Path $resolvedInstallRoot "versions").TrimEnd("\\") + "\\"

if (-not $resolvedVersionRoot.StartsWith(
    $versionsPrefix,
    [StringComparison]::OrdinalIgnoreCase
)) {{
    throw "Refusing to remove path outside install root"
}}

$wrapperPath = [string]$state.wrapper_path

if (Test-Path -LiteralPath $wrapperPath) {{
    Remove-Item -LiteralPath $wrapperPath -Force
}}
if (Test-Path -LiteralPath $CurrentFile) {{
    Remove-Item -LiteralPath $CurrentFile -Force
}}
if (Test-Path -LiteralPath $resolvedVersionRoot) {{
    Remove-Item -LiteralPath $resolvedVersionRoot -Recurse -Force
}}

Remove-Item -LiteralPath $StateFile -Force

$versionsRoot = Join-Path $resolvedInstallRoot "versions"
if (
    (Test-Path -LiteralPath $versionsRoot)
    -and -not (
        Get-ChildItem -LiteralPath $versionsRoot -Force |
        Select-Object -First 1
    )
) {{
    Remove-Item -LiteralPath $versionsRoot -Force
}}

if (
    (Test-Path -LiteralPath $resolvedInstallRoot)
    -and -not (
        Get-ChildItem -LiteralPath $resolvedInstallRoot -Force |
        Select-Object -First 1
    )
) {{
    Remove-Item -LiteralPath $resolvedInstallRoot -Force
}}

Write-Host "$Product uninstalled successfully."
'''


def write_uninstaller(
    spec: UninstallerSpec,
    destination: str | Path,
) -> UninstallerArtifact:
    path = Path(destination).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    if spec.kind == "shell":
        content = render_unix_uninstaller(spec)
        encoding = "utf-8"
        newline = "\n"
    else:
        content = render_windows_uninstaller(spec)
        encoding = "utf-8-sig"
        newline = "\r\n"

    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        content,
        encoding=encoding,
        newline=newline,
    )
    if spec.kind == "shell":
        os.chmod(temporary, 0o755)

    os.replace(temporary, path)

    return UninstallerArtifact(
        kind=spec.kind,
        path=str(path),
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        size_bytes=path.stat().st_size,
    )
