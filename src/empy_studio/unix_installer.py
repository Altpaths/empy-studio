from __future__ import annotations

import hashlib
import json
import os
import shlex
import stat
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from .platform_support import parse_target

UnixTarget = Literal[
    "macos-arm64",
    "macos-x86_64",
    "linux-arm64",
    "linux-x86_64",
]

_ENTRYPOINT_MODULES = {
    "empy": "empy_studio.cli",
    "empy-web": "empy_studio.web_desktop",
    "empy-desktop": "empy_studio.desktop.shell",
}


@dataclass(frozen=True)
class UnixInstallerSpec:
    product: str
    version: str
    target: UnixTarget
    package_url: str
    package_sha256: str
    package_filename: str
    minimum_python: str
    entrypoint: str = "empy"
    install_root: str = "${HOME}/.local/share/empy-studio"
    bin_dir: str = "${HOME}/.local/bin"

    def validate(self) -> None:
        spec = parse_target(self.target)
        if spec.operating_system not in {"macos", "linux"}:
            raise ValueError(
                "Unix installer target must be macOS or Linux"
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
                "Unix installer package must be a wheel or ZIP"
            )
        if len(self.package_sha256) != 64 or any(
            character not in "0123456789abcdef"
            for character in self.package_sha256.lower()
        ):
            raise ValueError(
                "Package SHA-256 must be a "
                "64-character hexadecimal digest"
            )
        python_parts = self.minimum_python.split(".")
        if (
            len(python_parts) != 2
            or not all(part.isdigit() for part in python_parts)
        ):
            raise ValueError(
                "minimum_python must use MAJOR.MINOR format"
            )
        if not self.entrypoint.strip() or "/" in self.entrypoint:
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
class UnixInstallerArtifact:
    target: UnixTarget
    path: str
    sha256: str
    size_bytes: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _shell(value: str) -> str:
    return shlex.quote(value)


def render_unix_installer(
    spec: UnixInstallerSpec,
) -> str:
    spec.validate()
    minimum_major, minimum_minor = spec.minimum_python.split(".")
    entrypoint_module = _ENTRYPOINT_MODULES[spec.entrypoint]

    return f'''#!/bin/sh
set -eu

PRODUCT={_shell(spec.product)}
VERSION={_shell(spec.version)}
TARGET={_shell(spec.target)}
PACKAGE_URL={_shell(spec.package_url)}
PACKAGE_SHA256={_shell(spec.package_sha256.lower())}
PACKAGE_FILENAME={_shell(spec.package_filename)}
MINIMUM_PYTHON={_shell(spec.minimum_python)}
MINIMUM_PYTHON_MAJOR={_shell(minimum_major)}
MINIMUM_PYTHON_MINOR={_shell(minimum_minor)}
ENTRYPOINT={_shell(spec.entrypoint)}
ENTRYPOINT_MODULE={_shell(entrypoint_module)}
INSTALL_ROOT={_shell(spec.install_root)}
BIN_DIR={_shell(spec.bin_dir)}

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
BIN_DIR="$(expand_home "$BIN_DIR")"
VERSION_ROOT="$INSTALL_ROOT/versions/$VERSION"
CURRENT_LINK="$INSTALL_ROOT/current"
STATE_FILE="$INSTALL_ROOT/install-state.json"
WRAPPER_PATH="$BIN_DIR/$ENTRYPOINT"

fail() {{
    printf 'ERROR: %s\\n' "$1" >&2
    exit 1
}}

command_exists() {{
    command -v "$1" >/dev/null 2>&1
}}

detect_platform() {{
    os_name="$(uname -s)"
    machine="$(uname -m)"

    case "$os_name" in
        Darwin) os_name="macos" ;;
        Linux) os_name="linux" ;;
        *) fail "Unsupported operating system: $os_name" ;;
    esac

    case "$machine" in
        arm64|aarch64) machine="arm64" ;;
        x86_64|amd64) machine="x86_64" ;;
        *) fail "Unsupported architecture: $machine" ;;
    esac

    detected="$os_name-$machine"
    if [ "$detected" != "$TARGET" ]; then
        fail "Installer target $TARGET does not match detected platform $detected"
    fi
}}

find_python() {{
    for candidate in python3 python; do
        if command_exists "$candidate"; then
            if "$candidate" - "$MINIMUM_PYTHON_MAJOR" "$MINIMUM_PYTHON_MINOR" <<'PY'
import sys
required = (int(sys.argv[1]), int(sys.argv[2]))
raise SystemExit(0 if sys.version_info[:2] >= required else 1)
PY
            then
                PYTHON="$candidate"
                export PYTHON
                return
            fi
        fi
    done
    fail "Python $MINIMUM_PYTHON or newer is required"
}}

download_package() {{
    destination="$1"
    case "$PACKAGE_URL" in
        file://*)
            source_path="${{PACKAGE_URL#file://}}"
            [ -f "$source_path" ] || fail "Local package does not exist"
            cp "$source_path" "$destination"
            ;;
        https://*)
            command_exists curl || fail "curl is required"
            curl --fail --location --proto '=https' --tlsv1.2 \
                --retry 3 --retry-delay 1 \
                --output "$destination" "$PACKAGE_URL"
            ;;
        *)
            fail "Unsupported package URL"
            ;;
    esac
}}

calculate_sha256() {{
    file_path="$1"
    if command_exists shasum; then
        shasum -a 256 "$file_path" | awk '{{print $1}}'
    elif command_exists sha256sum; then
        sha256sum "$file_path" | awk '{{print $1}}'
    else
        "$PYTHON" - "$file_path" <<'PY'
import hashlib
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
digest = hashlib.sha256()
with path.open("rb") as handle:
    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
        digest.update(chunk)
print(digest.hexdigest())
PY
    fi
}}

write_state() {{
    "$PYTHON" - "$STATE_FILE" "$PRODUCT" "$VERSION" "$TARGET" \
        "$PACKAGE_SHA256" "$VERSION_ROOT" "$WRAPPER_PATH" <<'PY'
import json
import os
import pathlib
import sys
import tempfile

(
    state_path,
    product,
    version,
    target,
    package_sha256,
    version_root,
    wrapper_path,
) = sys.argv[1:]

payload = {{
    "schema_version": 1,
    "product": product,
    "version": version,
    "target": target,
    "package_sha256": package_sha256,
    "version_root": version_root,
    "wrapper_path": wrapper_path,
}}

path = pathlib.Path(state_path)
path.parent.mkdir(parents=True, exist_ok=True)
with tempfile.NamedTemporaryFile(
    "w",
    encoding="utf-8",
    dir=path.parent,
    delete=False,
) as handle:
    json.dump(payload, handle, ensure_ascii=False, indent=2)
    handle.write("\\n")
    temporary = pathlib.Path(handle.name)
os.replace(temporary, path)
PY
}}

install_package() {{
    umask 077
    mkdir -p "$INSTALL_ROOT/versions" "$BIN_DIR"

    temporary_root="$(mktemp -d "${{TMPDIR:-/tmp}}/empy-install.XXXXXX")"
    trap 'rm -rf "$temporary_root"' EXIT HUP INT TERM

    package_path="$temporary_root/$PACKAGE_FILENAME"
    staged_root="$temporary_root/version"

    download_package "$package_path"

    actual_sha256="$(calculate_sha256 "$package_path")"
    [ "$actual_sha256" = "$PACKAGE_SHA256" ] \
        || fail "Package SHA-256 mismatch"

    "$PYTHON" -m venv "$staged_root/venv"
    "$staged_root/venv/bin/python" -m pip install \
        --disable-pip-version-check \
        --no-input \
        --upgrade \
        "$package_path"

    "$staged_root/venv/bin/python" - "$ENTRYPOINT_MODULE" <<'PY'
import importlib
import sys
importlib.import_module(sys.argv[1])
PY

    [ ! -e "$VERSION_ROOT" ] \
        || fail "Version is already installed: $VERSION"

    mv "$staged_root" "$VERSION_ROOT"

    # pip-generated console scripts keep the absolute interpreter path of the
    # staging venv. Reinstall from the already verified local wheel after the
    # move so every script points at the final, relocatable venv.
    "$VERSION_ROOT/venv/bin/python" -m pip install \
        --disable-pip-version-check \
        --no-input \
        --no-deps \
        --force-reinstall \
        "$package_path"

    temporary_link="$INSTALL_ROOT/.current-$VERSION"
    ln -s "$VERSION_ROOT" "$temporary_link"
    mv -f "$temporary_link" "$CURRENT_LINK"

    temporary_wrapper="$BIN_DIR/.${{ENTRYPOINT}}-$VERSION"
    cat > "$temporary_wrapper" <<WRAPPER
#!/bin/sh
exec "$CURRENT_LINK/venv/bin/python" -m "$ENTRYPOINT_MODULE" "\\$@"
WRAPPER
    chmod 0755 "$temporary_wrapper"
    mv -f "$temporary_wrapper" "$WRAPPER_PATH"

    write_state

    trap - EXIT HUP INT TERM
    rm -rf "$temporary_root"

    printf '%s %s installed successfully.\\n' "$PRODUCT" "$VERSION"
    printf 'Command: %s\\n' "$WRAPPER_PATH"

    case ":${{PATH}}:" in
        *":${{BIN_DIR}}:"*) ;;
        *)
            printf 'Add %s to PATH to run %s directly.\\n' \
                "$BIN_DIR" "$ENTRYPOINT"
            ;;
    esac
}}

detect_platform
find_python
install_package
'''


def write_unix_installer(
    spec: UnixInstallerSpec,
    destination: str | Path,
) -> UnixInstallerArtifact:
    path = Path(destination).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        render_unix_installer(spec),
        encoding="utf-8",
        newline="\n",
    )
    os.chmod(
        temporary,
        stat.S_IRUSR
        | stat.S_IWUSR
        | stat.S_IXUSR
        | stat.S_IRGRP
        | stat.S_IXGRP
        | stat.S_IROTH
        | stat.S_IXOTH,
    )
    os.replace(temporary, path)

    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return UnixInstallerArtifact(
        target=spec.target,
        path=str(path),
        sha256=digest,
        size_bytes=path.stat().st_size,
    )


def save_unix_installer_spec(
    spec: UnixInstallerSpec,
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
