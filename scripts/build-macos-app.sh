#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
OUT=${1:-"$ROOT/dist"}
VERSION=${EMPY_DESKTOP_VERSION:-1.1.1}
APP="$OUT/Empy Studio.app"
CONTENTS="$APP/Contents"
RESOURCES="$CONTENTS/Resources"
APP_SOURCE="$RESOURCES/app"
RUNTIME="$RESOURCES/runtime"

rm -rf "$APP"
mkdir -p "$APP_SOURCE" "$RUNTIME/lib" "$CONTENTS/MacOS"

# Copy the application, including vendor dependencies, but never copy secrets,
# historical fixtures, local databases, or build metadata into the bundle.
rsync -a --delete \
    --exclude '.git/' \
    --exclude '.env' \
    --exclude '.empy/' \
    --exclude 'database/database.sqlite' \
    --exclude 'storage/app/*' \
    --exclude 'storage/framework/*' \
    --exclude 'storage/logs/*' \
    --exclude 'dist/' \
    --exclude 'desktop/' \
    "$ROOT/" "$APP_SOURCE/"

mkdir -p "$APP_SOURCE/storage/app" "$APP_SOURCE/storage/framework/cache" \
    "$APP_SOURCE/storage/framework/sessions" "$APP_SOURCE/storage/framework/views" \
    "$APP_SOURCE/storage/logs"

PHP_BIN=${EMPY_PHP_BIN:-$(command -v php || true)}
if [ -z "$PHP_BIN" ] || [ ! -x "$PHP_BIN" ]; then
    echo "A PHP 8.3+ executable is required to build the macOS bundle." >&2
    exit 1
fi

PHP_BIN=$(realpath "$PHP_BIN")
cp "$PHP_BIN" "$RUNTIME/php"
chmod 755 "$RUNTIME/php"

# Bundle non-system Homebrew dylibs used by PHP and rewrite their load paths so
# the application does not depend on the builder's /opt/homebrew installation.
queue="$RUNTIME/.queue"
seen="$RUNTIME/.seen"
printf '%s\n' "$RUNTIME/php" > "$queue"
: > "$seen"

# Homebrew libraries sometimes refer to a sibling dependency through
# @loader_path/lib or @rpath. Once the library is moved into the single
# runtime/lib directory those paths no longer point at the sibling. Resolve
# those references from the builder's Homebrew prefixes, copy the dependency,
# and rewrite the reference relative to the bundled library directory.
find_homebrew_library() {
    library_name=$1
    for prefix in /opt/homebrew/opt /usr/local/opt; do
        [ -d "$prefix" ] || continue
        candidate=$(find -L "$prefix" -type f -name "$library_name" -print -quit 2>/dev/null || true)
        if [ -n "$candidate" ]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done

    return 1
}

while [ -s "$queue" ]; do
    file=$(head -n 1 "$queue")
    tail -n +2 "$queue" > "$queue.next"
    mv "$queue.next" "$queue"
    [ -f "$file" ] || continue
    grep -Fqx "$file" "$seen" 2>/dev/null && continue
    printf '%s\n' "$file" >> "$seen"
    otool -L "$file" 2>/dev/null | tail -n +2 | sed 's/^[[:space:]]*//' | sed 's/ (.*$//' | while IFS= read -r dep; do
        [ -n "$dep" ] || continue
        name=$(basename "$dep")
        source="$dep"
        case "$dep" in
            /opt/homebrew/*|/usr/local/*)
                [ -f "$source" ] || continue
                ;;
            @loader_path/lib/*|@loader_path/*|@rpath/*)
                source=$(find_homebrew_library "$name" || true)
                [ -n "$source" ] || continue
                ;;
            *) continue ;;
        esac

        target="$RUNTIME/lib/$name"
        if [ ! -f "$target" ]; then cp "$source" "$target"; chmod 755 "$target"; fi
        if [ "$file" = "$RUNTIME/php" ]; then
            reference="@loader_path/lib/$name"
        else
            reference="@loader_path/$name"
        fi
        install_name_tool -change "$dep" "$reference" "$file" 2>/dev/null || true
        printf '%s\n' "$target" >> "$queue"
    done
done
rm -f "$seen" "$queue"

cat > "$RUNTIME/php.ini" <<'INI'
date.timezone=UTC
memory_limit=512M
display_errors=0
log_errors=1
error_log=/dev/stderr
INI

# Prefer the native Codex CLI when the builder provides one. A native release
# is downloaded only when the installed command is a Node wrapper; credentials
# are never copied into the bundle.
CODEX_BIN=${EMPY_CODEX_BIN:-}
if [ -z "$CODEX_BIN" ] && command -v codex >/dev/null 2>&1; then CODEX_BIN=$(command -v codex); fi
if [ -n "$CODEX_BIN" ] && file "$CODEX_BIN" | grep -q 'Mach-O'; then
    cp "$(realpath "$CODEX_BIN")" "$RUNTIME/codex"
elif [ -n "${EMPY_CODEX_RELEASE_URL:-}" ]; then
    curl -fsSL "$EMPY_CODEX_RELEASE_URL" -o "$OUT/codex.tar.gz"
    tar -xzf "$OUT/codex.tar.gz" -C "$OUT"
    CODEX_EXTRACTED=$(find "$OUT" -type f -name codex -perm -u+x -print -quit)
    [ -n "$CODEX_EXTRACTED" ] || { echo "Codex release did not contain a native codex binary." >&2; exit 1; }
    cp "$CODEX_EXTRACTED" "$RUNTIME/codex"
    rm -f "$OUT/codex.tar.gz"
fi
[ -x "$RUNTIME/codex" ] && chmod 755 "$RUNTIME/codex" || true
if [ "${EMPY_REQUIRE_CODEX:-false}" = "true" ] && [ ! -x "$RUNTIME/codex" ]; then
    echo "A native arm64 Codex binary is required for this desktop bundle." >&2
    exit 1
fi

cat > "$CONTENTS/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
    <key>CFBundleDisplayName</key><string>Empy Studio</string>
    <key>CFBundleExecutable</key><string>Empy Studio</string>
    <key>CFBundleIdentifier</key><string>dev.altpaths.empy-studio</string>
    <key>CFBundleName</key><string>Empy Studio</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleShortVersionString</key><string>$VERSION</string>
    <key>CFBundleVersion</key><string>$VERSION</string>
    <key>LSMinimumSystemVersion</key><string>13.0</string>
</dict></plist>
PLIST

cat > "$CONTENTS/MacOS/Empy Studio" <<'LAUNCHER'
#!/bin/sh
set -eu

CONTENTS=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
APP_ROOT="$CONTENTS/Resources/app"
RUNTIME="$CONTENTS/Resources/runtime"
DATA_ROOT="${HOME}/Library/Application Support/Empy Studio"
mkdir -p "$DATA_ROOT" "$DATA_ROOT/storage/app" "$DATA_ROOT/storage/framework/cache" \
    "$DATA_ROOT/storage/framework/sessions" "$DATA_ROOT/storage/framework/views" "$DATA_ROOT/storage/logs"

ENV_FILE="$DATA_ROOT/.env"
if [ ! -f "$ENV_FILE" ]; then
    cp "$APP_ROOT/.env.example" "$ENV_FILE"
    APP_KEY=$(
        APP_ENV=local APP_KEY= "$RUNTIME/php" -c "$RUNTIME/php.ini" -r 'echo "base64:".base64_encode(random_bytes(32));' 2>/dev/null || true
    )
    if [ -n "$APP_KEY" ]; then printf '\nAPP_KEY=%s\n' "$APP_KEY" >> "$ENV_FILE"; fi
fi

set_env() {
    key=$1; value=$2
    if grep -q "^${key}=" "$ENV_FILE" 2>/dev/null; then
        sed -i '' "s#^${key}=.*#${key}=${value}#" "$ENV_FILE"
    else
        printf '%s=%s\n' "$key" "$value" >> "$ENV_FILE"
    fi
}

set_env APP_ENV local
set_env APP_URL http://127.0.0.1:18765
set_env APP_STORAGE_PATH "$DATA_ROOT/storage"
set_env DB_CONNECTION sqlite
set_env DB_DATABASE "$DATA_ROOT/database.sqlite"
if ! grep -q '^EMPY_PROVIDER_ORDER=' "$ENV_FILE" 2>/dev/null; then
    set_env EMPY_PROVIDER_ORDER codex,gemini,ollama,openai_compatible
fi
set_env EMPY_VERSION "__EMPY_VERSION__"
if [ -x "$RUNTIME/codex" ]; then set_env EMPY_CODEX_BIN "$RUNTIME/codex"; fi

PHP="$RUNTIME/php"
[ -x "$PHP" ] || PHP=$(command -v php || true)
[ -x "$PHP" ] || { open -a TextEdit "$ENV_FILE"; exit 1; }

cd "$APP_ROOT"
touch "$DATA_ROOT/database.sqlite"
export APP_ENV=local
export APP_KEY=$(sed -n 's/^APP_KEY=//p' "$ENV_FILE" | tail -1)
export APP_STORAGE_PATH="$DATA_ROOT/storage"
export DB_CONNECTION=sqlite
export DB_DATABASE="$DATA_ROOT/database.sqlite"
export EMPY_PROVIDER_ORDER=$(sed -n 's/^EMPY_PROVIDER_ORDER=//p' "$ENV_FILE" | tail -1)
export EMPY_VERSION=$(sed -n 's/^EMPY_VERSION=//p' "$ENV_FILE" | tail -1)
export EMPY_CODEX_BIN="${RUNTIME}/codex"

MIGRATION_LOG="$DATA_ROOT/migrate.log"
if ! "$PHP" -c "$RUNTIME/php.ini" artisan migrate --force >"$MIGRATION_LOG" 2>&1; then
    /usr/bin/osascript -e 'display alert "Empy Studio could not initialize" message "Database setup failed. The migration log will open so the cause is visible." as critical' >/dev/null 2>&1 || true
    open -a TextEdit "$MIGRATION_LOG" >/dev/null 2>&1 || true
    exit 1
fi
PORT=18765
while /usr/bin/nc -z 127.0.0.1 "$PORT" >/dev/null 2>&1; do PORT=$((PORT + 1)); done
export APP_URL="http://127.0.0.1:${PORT}"
nohup "$PHP" -c "$RUNTIME/php.ini" artisan serve --host=127.0.0.1 --port="$PORT" >> "$DATA_ROOT/server.log" 2>&1 </dev/null &
printf '%s\n' "$!" > "$DATA_ROOT/server.pid"
ready=0
for attempt in $(jot 30 1); do
    if /usr/bin/nc -z 127.0.0.1 "$PORT" >/dev/null 2>&1; then ready=1; break; fi
    sleep 0.2
done
if [ "$ready" -ne 1 ]; then
    /usr/bin/osascript -e 'display alert "Empy Studio could not start" message "The local server did not become ready. The server log will open so the cause is visible." as critical' >/dev/null 2>&1 || true
    open -a TextEdit "$DATA_ROOT/server.log" >/dev/null 2>&1 || true
    exit 1
fi
open "http://127.0.0.1:${PORT}"
LAUNCHER
chmod 755 "$CONTENTS/MacOS/Empy Studio"
sed -i '' "s/__EMPY_VERSION__/$VERSION/g" "$CONTENTS/MacOS/Empy Studio"

if command -v xattr >/dev/null 2>&1; then
    # Finder provenance/resource-fork metadata makes an otherwise valid
    # ad-hoc signature fail on macOS. It is not part of the application.
    xattr -cr "$APP"
    for attribute in com.apple.FinderInfo com.apple.ResourceFork 'com.apple.fileprovider.fpfs#P'; do
        xattr -r -d "$attribute" "$APP" 2>/dev/null || true
    done
fi
if command -v codesign >/dev/null 2>&1; then
    # install_name_tool invalidates the original Homebrew signatures. These
    # runtime binaries live under Resources rather than a nested framework, so
    # codesign --deep does not reliably re-sign them. Sign and verify every
    # Mach-O first, then sign and verify the enclosing app.
    find "$RUNTIME" -type f -print | while IFS= read -r binary; do
        if file "$binary" 2>/dev/null | grep -q 'Mach-O'; then
            codesign --force --sign - "$binary" >/dev/null 2>&1
            codesign --verify --strict "$binary" >/dev/null 2>&1
        fi
    done
    codesign --force --deep --sign - "$APP" >/dev/null 2>&1
    codesign --verify --deep --strict "$APP" >/dev/null 2>&1
fi

mkdir -p "$OUT"
ARCHIVE="$OUT/empy-studio-macos-arm64-$VERSION.zip"
APP_NAME=$(basename "$APP")
rm -f "$ARCHIVE"
(cd "$OUT" && COPYFILE_DISABLE=1 zip -qry -X "$ARCHIVE" "$APP_NAME")
shasum -a 256 "$ARCHIVE" > "$ARCHIVE.sha256"
printf '%s\n' "$ARCHIVE"
