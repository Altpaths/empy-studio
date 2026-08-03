from __future__ import annotations

import math
import re
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .common import load_json, save_json

_WORD_RE = re.compile(r"[A-Za-z0-9_\-\.\u0600-\u06FF]+")
_DEFAULT_MAX_BYTES = 64_000
_PRIORITY_DOCS = (
    "knowledge/PROJECT_IDENTITY.md",
    "knowledge/DECISIONS.md",
)


@dataclass(frozen=True)
class Candidate:
    path: str
    size: int
    score: int
    reason: str


def _terms(text: str) -> set[str]:
    return {term.lower() for term in _WORD_RE.findall(text) if len(term) > 1}


def _safe_member(name: str) -> bool:
    path = PurePosixPath(name)
    return not path.is_absolute() and ".." not in path.parts


def _score_path(path: str, request_terms: set[str], explicit: set[str]) -> Candidate:
    normalized = path.lower()
    if path in explicit:
        return Candidate(path=path, size=0, score=10_000, reason="explicit")

    path_terms = _terms(normalized.replace("/", " "))
    overlap = request_terms.intersection(path_terms)
    score = len(overlap) * 20
    suffix = Path(path).suffix.lower()
    source_suffixes = {
        ".py", ".php", ".ts", ".tsx", ".js", ".jsx", ".html",
        ".css", ".md", ".json", ".toml", ".yml", ".yaml",
    }
    if suffix in source_suffixes:
        score += 2
    if any(part in {"vendor", "dist", "build", "node_modules"} for part in PurePosixPath(path).parts):
        score -= 100
    return Candidate(path=path, size=0, score=score, reason="keyword" if overlap else "fallback")


def _read_snapshot_member(snapshot: Path, member: str) -> bytes:
    with zipfile.ZipFile(snapshot) as archive:
        if member not in archive.namelist():
            raise FileNotFoundError(f"file not found in baseline snapshot: {member}")
        if not _safe_member(member):
            raise ValueError(f"unsafe snapshot path: {member}")
        return archive.read(member)


def _candidate_files(
    *,
    vault: Path,
    request: dict[str, Any],
    explicit_files: list[str],
) -> list[Candidate]:
    baseline = load_json(vault / "baseline" / "manifest.json")
    text = " ".join(
        str(value)
        for value in (
            request.get("text", ""),
            request.get("goal", ""),
            request.get("acceptance_criteria", ""),
            request.get("agent", ""),
        )
    )
    request_terms = _terms(text)
    explicit = set(explicit_files)
    for key in ("files", "read_scope"):
        values = request.get(key, [])
        if isinstance(values, list):
            explicit.update(str(value) for value in values)

    candidates: list[Candidate] = []
    for item in baseline.get("files", []):
        path = str(item["path"])
        candidate = _score_path(path, request_terms, explicit)
        candidates.append(
            Candidate(
                path=path,
                size=int(item.get("size", 0)),
                score=candidate.score,
                reason=candidate.reason,
            )
        )
    return sorted(candidates, key=lambda item: (-item.score, item.size, item.path))


def build_context(
    *,
    vault_root: str | Path,
    request_path: str | Path,
    output_dir: str | Path,
    max_bytes: int = _DEFAULT_MAX_BYTES,
    explicit_files: list[str] | None = None,
) -> dict[str, Any]:
    if max_bytes < 1_024:
        raise ValueError("max_bytes must be at least 1024")

    vault = Path(vault_root).expanduser().resolve()
    request_file = Path(request_path).expanduser().resolve()
    output = Path(output_dir).expanduser().resolve()
    metadata = load_json(vault / "vault.json")
    request = load_json(request_file)
    snapshot_value = metadata.get("source_snapshot")
    if not snapshot_value:
        raise ValueError("Project Vault has no baseline source snapshot")
    snapshot = vault / str(snapshot_value)
    if not snapshot.exists():
        raise FileNotFoundError("Project Vault baseline source snapshot is missing")

    if output.exists():
        shutil.rmtree(output)
    files_dir = output / "files"
    files_dir.mkdir(parents=True)

    fixed_sections: list[tuple[str, bytes]] = []
    for relative in _PRIORITY_DOCS:
        path = vault / relative
        if path.exists():
            fixed_sections.append((relative, path.read_bytes()))
    fixed_sections.append((request_file.name, request_file.read_bytes()))

    used = sum(len(content) for _, content in fixed_sections)
    selected: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for candidate in _candidate_files(
        vault=vault,
        request=request,
        explicit_files=explicit_files or [],
    ):
        if candidate.score <= 0 and selected:
            skipped.append({"path": candidate.path, "reason": "low_relevance"})
            continue
        if used + candidate.size > max_bytes:
            skipped.append({"path": candidate.path, "reason": "budget"})
            continue
        content = _read_snapshot_member(snapshot, candidate.path)
        destination = files_dir / candidate.path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        used += len(content)
        selected.append(
            {
                "path": candidate.path,
                "bytes": len(content),
                "score": candidate.score,
                "reason": candidate.reason,
            }
        )

    context_manifest: dict[str, Any] = {
        "schema_version": 1,
        "engine": "empy_studio.context",
        "project_id": metadata["project_id"],
        "request_id": request.get("request_id"),
        "agent": request.get("agent", "primary"),
        "max_bytes": max_bytes,
        "used_bytes": used,
        "estimated_tokens": math.ceil(used / 4),
        "selected_files": selected,
        "skipped_files": skipped,
        "status": "ready",
    }
    save_json(output / "context.json", context_manifest)

    lines = [
        "# Empy Studio Context Package",
        "",
        f"- Project: `{metadata['project_id']}`",
        f"- Request: `{request.get('request_id', 'unknown')}`",
        f"- Agent: `{request.get('agent', 'primary')}`",
        f"- Budget: {max_bytes} bytes",
        f"- Used: {used} bytes (~{context_manifest['estimated_tokens']} tokens)",
        "",
        "## Instructions",
        "",
        (
            "Read `request.json`, then the project identity and locked decisions. "
            "Read only the selected files under `files/`. Do not scan the complete "
            "repository unless the task is blocked and the primary agent expands scope."
        ),
        "",
        "## Selected files",
        "",
    ]
    lines.extend(f"- `{item['path']}` — {item['reason']}" for item in selected)
    (output / "CONTEXT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    shutil.copy2(request_file, output / "request.json")
    for relative, content in fixed_sections[:-1]:
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    return context_manifest
