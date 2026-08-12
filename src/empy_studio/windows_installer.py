from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .platform_support import parse_target

_ENTRYPOINT_MODULES = {
    "empy": "empy_studio.cli",
    "empy-web": "empy_studio.web_desktop",
    "empy-desktop": "empy_studio.desktop.shell",
}


@dataclass(frozen=True)
class WindowsInstallerSpec:
    product: str
    version: str
    target: str
    package_url: str
    package_sha256: str
    package_filename: str
    minimum_python: str
    entrypoint: str = "empy"
    install_root: str = "$env:LOCALAPPDATA\\EmpyStudio"
    bin_dir: str = "$env:LOCALAPPDATA\\Microsoft\\WindowsApps"

    def validate(self) -> None:
        spec = parse_target(self.target)
        if spec.operating_system != "windows":
            raise ValueError(
                "Windows installer target must be Windows"
            )
        if not self.product.strip():
            raise ValueError("Product cannot be empty")
        if not self.version.strip():
            raise ValueError("Version cannot be empty")
        if not self.package_url.startswith(("https://", "file://")):
            raise ValueError(
                "Package URL must use https:// or file://"
            )
        if Path(self.package_filename).name != self.package_filename:
            raise ValueError(
                "Package filename must not contain a path"
            )
        if not self.package_filename.endswith((".whl", ".zip")):
            raise ValueError(
                "Windows installer package must be a wheel or ZIP"
            )
        if len(self.package_sha256) != 64 or any(
            character not in "0123456789abcdef"
            for character in self.package_sha256.lower()
        ):
            raise ValueError(
                "Package SHA-256 must be a "
                "64-character hexadecimal digest"
            )
        parts = self.minimum_python.split(".")
        if len(parts) != 2 or not all(part.isdigit() for part in parts):
            raise ValueError(
                "minimum_python must use MAJOR.MINOR format"
            )
        if (
            not self.entrypoint.strip()
            or "\\" in self.entrypoint
            or "/" in self.entrypoint
        ):
            raise ValueError(
                "Entrypoint must be a command name"
            )
        if self.entrypoint not in _ENTRYPOINT_MODULES:
            raise ValueError(
                "Entrypoint must be one of: "
                + ", ".join(sorted(_ENTRYPOINT_MODULES))
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WindowsInstallerArtifact:
    target: str
    path: str
    sha256: str
    size_bytes: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def render_windows_installer(
    spec: WindowsInstallerSpec,
) -> str:
    spec.validate()
    minimum_major, minimum_minor = spec.minimum_python.split(".")
    entrypoint_module = _ENTRYPOINT_MODULES[spec.entrypoint]

    return f'''#requires -Version 5.1
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Product = {_ps_quote(spec.product)}
$Version = {_ps_quote(spec.version)}
$Target = {_ps_quote(spec.target)}
$PackageUrl = {_ps_quote(spec.package_url)}
$PackageSha256 = {_ps_quote(spec.package_sha256.lower())}
$PackageFilename = {_ps_quote(spec.package_filename)}
$MinimumPython = {_ps_quote(spec.minimum_python)}
$MinimumPythonMajor = {minimum_major}
$MinimumPythonMinor = {minimum_minor}
$Entrypoint = {_ps_quote(spec.entrypoint)}
$EntrypointModule = {_ps_quote(entrypoint_module)}
$InstallRoot = {_ps_quote(spec.install_root)}
$BinDir = {_ps_quote(spec.bin_dir)}

function Expand-EnvironmentPath {{
    param([string]$Value)
    $expanded = $ExecutionContext.InvokeCommand.ExpandString($Value)
    return [Environment]::ExpandEnvironmentVariables($expanded)
}}

$InstallRoot = Expand-EnvironmentPath $InstallRoot
$BinDir = Expand-EnvironmentPath $BinDir
$VersionRoot = Join-Path $InstallRoot ("versions\\$Version")
$CurrentFile = Join-Path $InstallRoot "current.json"
$StateFile = Join-Path $InstallRoot "install-state.json"
$WrapperPath = Join-Path $BinDir "$Entrypoint.cmd"

function Fail {{
    param([string]$Message)
    throw $Message
}}

function Test-SupportedPlatform {{
    if (-not [Environment]::Is64BitOperatingSystem) {{
        Fail "A 64-bit Windows operating system is required"
    }}

    if ($env:PROCESSOR_ARCHITECTURE -notin @("AMD64", "x86")) {{
        Fail "Unsupported Windows architecture"
    }}

    if ($Target -ne "windows-x86_64") {{
        Fail "Installer target does not match Windows x86_64"
    }}
}}

function Get-SupportedPython {{
    $candidates = @(
        @("py", "-3"),
        @("python", ""),
        @("python3", "")
    )

    foreach ($candidate in $candidates) {{
        $command = Get-Command $candidate[0] -ErrorAction SilentlyContinue
        if ($null -eq $command) {{
            continue
        }}

        $arguments = @()
        if ($candidate[1]) {{
            $arguments += $candidate[1]
        }}

        $code = "import sys; required=($MinimumPythonMajor,$MinimumPythonMinor); raise SystemExit(0 if sys.version_info[:2] >= required else 1)"
        & $candidate[0] @arguments -c $code 2>$null

        if ($LASTEXITCODE -eq 0) {{
            return [PSCustomObject]@{{
                Command = $candidate[0]
                PrefixArguments = $arguments
            }}
        }}
    }}

    Fail "Python $MinimumPython or newer is required"
}}

function Invoke-Python {{
    param(
        [Parameter(Mandatory=$true)]
        [object]$Python,
        [string[]]$Arguments
    )
    & $Python.Command @($Python.PrefixArguments) @Arguments
}}

function Download-Package {{
    param([string]$Destination)

    if ($PackageUrl.StartsWith("file://")) {{
        $source = $PackageUrl.Substring(7)
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {{
            Fail "Local package does not exist"
        }}
        Copy-Item -LiteralPath $source -Destination $Destination
        return
    }}

    if (-not $PackageUrl.StartsWith("https://")) {{
        Fail "Unsupported package URL"
    }}

    $previousProtocol = [Net.ServicePointManager]::SecurityProtocol
    try {{
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $PackageUrl -OutFile $Destination -UseBasicParsing
    }}
    finally {{
        [Net.ServicePointManager]::SecurityProtocol = $previousProtocol
    }}
}}

function Get-PackageSha256 {{
    param([string]$Path)

    $algorithm = [System.Security.Cryptography.SHA256]::Create()
    $stream = [System.IO.File]::OpenRead($Path)
    try {{
        return (
            [System.BitConverter]::ToString($algorithm.ComputeHash($stream))
        ).Replace("-", "").ToLowerInvariant()
    }}
    finally {{
        $stream.Dispose()
        $algorithm.Dispose()
    }}
}}

function Write-JsonAtomic {{
    param(
        [string]$Path,
        [object]$Value
    )

    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Path $parent -Force | Out-Null

    $temporary = "$Path.tmp"
    $Value |
        ConvertTo-Json -Depth 8 |
        Set-Content -LiteralPath $temporary -Encoding UTF8

    Move-Item -LiteralPath $temporary -Destination $Path -Force
}}

function Install-Package {{
    $python = Get-SupportedPython

    New-Item -ItemType Directory `
        -Path (Join-Path $InstallRoot "versions") `
        -Force | Out-Null

    New-Item -ItemType Directory `
        -Path $BinDir `
        -Force | Out-Null

    if (Test-Path -LiteralPath $VersionRoot) {{
        $existingState = $null
        if (Test-Path -LiteralPath $StateFile -PathType Leaf) {{
            try {{
                $existingState = Get-Content -LiteralPath $StateFile -Raw | ConvertFrom-Json
            }} catch {{
                $existingState = $null
            }}
        }}
        $existingPython = Join-Path $VersionRoot "venv\\Scripts\\python.exe"
        if ($null -ne $existingState -and $existingState.package_sha256 -eq $PackageSha256 -and (Test-Path -LiteralPath $existingPython -PathType Leaf)) {{
            Write-Host "$Product $Version is already installed and verified."
            Write-Host "Command: $WrapperPath"
            return
        }}
        Fail "Version $Version is already installed with a different or incomplete package; remove it before retrying"
    }}

    $temporaryRoot = Join-Path `
        ([IO.Path]::GetTempPath()) `
        ("empy-install-" + [Guid]::NewGuid().ToString("N"))

    New-Item -ItemType Directory `
        -Path $temporaryRoot `
        -Force | Out-Null

    try {{
        $packagePath = Join-Path $temporaryRoot $PackageFilename
        $stagedRoot = Join-Path $temporaryRoot "version"

        Download-Package $packagePath

        $actualSha256 = Get-PackageSha256 -Path $packagePath

        if ($actualSha256 -ne $PackageSha256) {{
            Fail "Package SHA-256 mismatch"
        }}

        Invoke-Python `
            -Python $python `
            -Arguments @(
                "-m",
                "venv",
                (Join-Path $stagedRoot "venv")
            )

        $venvPython = Join-Path `
            $stagedRoot `
            "venv\\Scripts\\python.exe"

        & $venvPython `
            -m pip install `
            --disable-pip-version-check `
            --no-input `
            --upgrade `
            $packagePath

        & $venvPython `
            -c `
            "import importlib,sys; importlib.import_module(sys.argv[1])" `
            $EntrypointModule
        if ($LASTEXITCODE -ne 0) {{
            Fail "Installed package did not provide entrypoint module: $EntrypointModule"
        }}

        $entrypointExe = Join-Path `
            $stagedRoot `
            "venv\\Scripts\\$Entrypoint.exe"

        $entrypointCmd = Join-Path `
            $stagedRoot `
            "venv\\Scripts\\$Entrypoint.cmd"

        if ((-not (Test-Path -LiteralPath $entrypointExe)) -and (-not (Test-Path -LiteralPath $entrypointCmd))) {{
            Fail "Installed package did not provide entrypoint"
        }}

        Move-Item `
            -LiteralPath $stagedRoot `
            -Destination $VersionRoot

        Write-JsonAtomic `
            -Path $CurrentFile `
            -Value @{{
                schema_version = 1
                version = $Version
                version_root = $VersionRoot
            }}

        $wrapperTemporary = "$WrapperPath.tmp"
        $wrapper = "@echo off`r`n`"$VersionRoot\\venv\\Scripts\\python.exe`" -m $EntrypointModule %*`r`n"
        Set-Content `
            -LiteralPath $wrapperTemporary `
            -Value $wrapper `
            -Encoding ASCII

        Move-Item `
            -LiteralPath $wrapperTemporary `
            -Destination $WrapperPath `
            -Force

        Write-JsonAtomic `
            -Path $StateFile `
            -Value @{{
                schema_version = 1
                product = $Product
                version = $Version
                target = $Target
                package_sha256 = $PackageSha256
                version_root = $VersionRoot
                wrapper_path = $WrapperPath
            }}

        Write-Host "$Product $Version installed successfully."
        Write-Host "Command: $WrapperPath"

        if (($env:PATH -split ";") -notcontains $BinDir) {{
            Write-Host "Add $BinDir to PATH to run $Entrypoint directly."
        }}
    }}
    finally {{
        if (Test-Path -LiteralPath $temporaryRoot) {{
            Remove-Item `
                -LiteralPath $temporaryRoot `
                -Recurse `
                -Force
        }}
    }}
}}

Test-SupportedPlatform
Install-Package
'''


def write_windows_installer(
    spec: WindowsInstallerSpec,
    destination: str | Path,
) -> WindowsInstallerArtifact:
    path = Path(destination).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        render_windows_installer(spec),
        encoding="utf-8-sig",
        newline="\r\n",
    )
    os.replace(temporary, path)

    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return WindowsInstallerArtifact(
        target=spec.target,
        path=str(path),
        sha256=digest,
        size_bytes=path.stat().st_size,
    )


def save_windows_installer_spec(
    spec: WindowsInstallerSpec,
    destination: str | Path,
) -> Path:
    spec.validate()

    path = Path(destination).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            spec.to_dict(),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return path
