#!/usr/bin/env bash
set -euo pipefail

version="${1:-1.0.0}"
output="${2:-dist/empy-studio-laravel-${version}-source.zip}"
mkdir -p "$(dirname "$output")"
git archive --format=zip --prefix="empy-studio-laravel-${version}/" HEAD \
  ':(exclude).empy/**' \
  -o "$output"
shasum -a 256 "$output" > "${output}.sha256"
printf '%s\n' "$output"
printf '%s\n' "${output}.sha256"
