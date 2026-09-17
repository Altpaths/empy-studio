"""Small, safe value objects for Empy Studio's durable failure memory.

The ledger deliberately stores a *diagnostic summary* rather than provider
transcripts.  This module owns the normalization and redaction rules used by
the SQLite adapter, so every caller gets the same bounded representation.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

FailureMemoryStatus = Literal["open", "resolved", "superseded"]

# These are storage limits, rather than UI suggestions.  Keeping them here
# makes it difficult for a future adapter to accidentally persist raw output.
MAX_PROJECT_ID_CHARS = 256
MAX_TASK_ID_CHARS = 256
MAX_KIND_CHARS = 80
MAX_SUMMARY_CHARS = 800
MAX_ACTION_CHARS = 800
MAX_EVIDENCE_ITEMS = 8
MAX_EVIDENCE_CHARS = 600
MAX_EVIDENCE_TOTAL_CHARS = 4_000
MAX_AFFECTED_PATHS = 32
MAX_AFFECTED_PATH_CHARS = 240
MAX_TASK_IDS = 32
MAX_MEMORY_ROWS_PER_PROJECT = 256
MAX_QUERY_LIMIT = 100
MAX_CONTEXT_HINT_CHARS = 2_400

_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WHITESPACE = re.compile(r"\s+")

# Credentials are redacted before any text is fingerprinted or persisted.
_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"(?i)(\b(?:api[_ -]?key|token|secret|password|passwd)\b\s*[:=]\s*)[^\s,;]+"),
        r"\1<redacted>",
    ),
    (
        re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"),
        "Bearer <redacted>",
    ),
    (re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{8,}\b"), "<redacted-key>"),
    (re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{8,}\b"), "<redacted-key>"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{8,}\b"), "<redacted-key>"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{8,}\b"), "<redacted-key>"),
    (
        re.compile(r"(?i)(\bauthorization\s*:\s*)([^\s,;]+)"),
        r"\1<redacted>",
    ),
)

# Only well-known absolute roots are replaced.  A slash in a URL or an error
# code such as ``/api/v1`` should remain useful diagnostic text.
_POSIX_PATH = re.compile(
    r"(?<![\w:])/(?:Users|home|private|tmp|var|opt|mnt|Volumes|Applications|Library|System|workspace|work|root)"
    r"(?:/[^\s'\"`<>;,)]*)*",
    re.IGNORECASE,
)
_WINDOWS_PATH = re.compile(r"(?<![\w])(?:[A-Za-z]:[\\/])[^\s'\"`<>;,)]*", re.IGNORECASE)
_UNC_PATH = re.compile(r"(?<![\w])\\\\[^\s'\"`<>;,)]*", re.IGNORECASE)

# These values vary between runs and must not split one incident into many
# records after a restart.  The replacement preserves the surrounding error.
_VOLATILE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f-]{27,}\b", re.IGNORECASE), "<id>"),
    (re.compile(r"\b(?:run|task|node|job|request|trace|attempt)[_-]?(?:id)?\s*[:=]\s*[A-Za-z0-9._-]+", re.IGNORECASE), "<id>"),
    (re.compile(r"\b[0-9a-f]{16,}\b", re.IGNORECASE), "<id>"),
    (
        re.compile(
            r"\b\d{4}-\d{2}-\d{2}[t ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:z|[+-]\d{2}:?\d{2})?\b",
            re.IGNORECASE,
        ),
        "<timestamp>",
    ),
    (re.compile(r"\b\d{10,13}\b"), "<timestamp>"),
    (re.compile(r"\b\d+(?:\.\d+)?\s*(?:seconds?|milliseconds?|ms|s)\b", re.IGNORECASE), "<duration>"),
    (re.compile(r"\b(?:line|column|col)\s*[:=]?\s*\d+\b", re.IGNORECASE), "<location>"),
)


def _require_text(value: object, name: str, *, max_chars: int | None = None) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if max_chars is not None and len(value) > max_chars:
        raise ValueError(f"{name} cannot exceed {max_chars} characters")
    return value


def _clean_text(value: str, *, max_chars: int) -> str:
    """Normalize and redact one bounded piece of diagnostic text."""

    cleaned = unicodedata.normalize("NFKC", value)
    cleaned = _CONTROL_CHARS.sub(" ", cleaned)
    for pattern, replacement in _SECRET_PATTERNS:
        cleaned = pattern.sub(replacement, cleaned)
    cleaned = _WINDOWS_PATH.sub("<path>", cleaned)
    cleaned = _UNC_PATH.sub("<path>", cleaned)
    cleaned = _POSIX_PATH.sub("<path>", cleaned)
    cleaned = _WHITESPACE.sub(" ", cleaned).strip()
    # Truncation happens after redaction so a secret at the end cannot survive
    # an early cut.  The ellipsis is stable and helps the UI explain that the
    # evidence was intentionally bounded.
    if len(cleaned) > max_chars:
        cleaned = cleaned[: max_chars - 1].rstrip() + "…"
    return cleaned


def sanitize_failure_text(value: str, *, max_chars: int = MAX_EVIDENCE_CHARS) -> str:
    """Return safe diagnostic text with secrets and host paths removed."""

    _require_text(value, "failure text")
    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    return _clean_text(value, max_chars=max_chars)


def normalize_failure_text(value: str) -> str:
    """Produce stable bounded text for matching incidents across runs."""

    normalized = _clean_text(_require_text(value, "failure text"), max_chars=MAX_SUMMARY_CHARS)
    for pattern, replacement in _VOLATILE_PATTERNS:
        normalized = pattern.sub(replacement, normalized)
    normalized = _WHITESPACE.sub(" ", normalized).strip().casefold()
    return normalized


def failure_fingerprint(
    context: str,
    *,
    kind: str = "",
    action: str = "",
    evidence: Sequence[str] = (),
) -> str:
    """Hash stable diagnostic identity while excluding volatile run details.

    ``context`` remains the first positional argument for easy use by runtime
    code.  ``kind`` and the first bounded evidence item add useful identity
    when two failure classes happen to use the same short summary.
    """

    parts = [normalize_failure_text(context)]
    if kind:
        parts.insert(0, normalize_failure_text(kind))
    # Actions are deliberately omitted from the identity when a summary is
    # present: changing guidance must not create a second incident.
    if action and not context.strip():
        parts.append(normalize_failure_text(action))
    if evidence and not context.strip():
        parts.extend(normalize_failure_text(item) for item in evidence[:2] if isinstance(item, str))
    canonical = "|".join(part for part in parts if part)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def normalize_supplied_fingerprint(value: str) -> str:
    """Validate an external fingerprint, hashing short values safely.

    Older recovery state sometimes contains a human label rather than a full
    digest.  Hashing that label lets the ledger accept it without persisting
    arbitrary text as an identity.
    """

    value = _require_text(value, "fingerprint").strip().casefold()
    if not value:
        raise ValueError("fingerprint cannot be empty")
    if _HEX_64.fullmatch(value):
        return value
    return failure_fingerprint(value)


def normalize_relative_path(value: str) -> str:
    """Validate a project-relative affected path.

    Absolute paths are rejected instead of guessed.  The surrounding failure
    text can still contain a redacted ``<path>`` marker, while this structured
    field remains safe for project-scoped matching.
    """

    value = _require_text(value, "affected path").strip().replace("\\", "/")
    if not value:
        raise ValueError("affected path cannot be empty")
    if value.startswith(("/", "//")) or re.match(r"^[A-Za-z]:/", value):
        raise ValueError("affected paths must be project-relative")
    parts = tuple(part for part in value.split("/") if part not in {"", "."})
    if not parts or ".." in parts:
        raise ValueError("affected path must stay inside the project")
    normalized = "/".join(parts)
    if len(normalized) > MAX_AFFECTED_PATH_CHARS:
        raise ValueError(f"affected path cannot exceed {MAX_AFFECTED_PATH_CHARS} characters")
    if any(_CONTROL_CHARS.search(part) for part in parts):
        raise ValueError("affected path contains control characters")
    return normalized


def normalize_affected_paths(values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError("affected_paths must be a sequence of strings")
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        path = normalize_relative_path(value)
        if path in seen:
            continue
        seen.add(path)
        normalized.append(path)
        if len(normalized) >= MAX_AFFECTED_PATHS:
            break
    return tuple(normalized)


def _normalize_evidence(values: Sequence[str], *, max_chars: int = MAX_EVIDENCE_CHARS) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError("evidence must be a sequence of strings")
    result: list[str] = []
    total = 0
    seen: set[str] = set()
    for value in values:
        text = sanitize_failure_text(_require_text(value, "evidence"), max_chars=max_chars)
        if not text or text in seen:
            continue
        available = MAX_EVIDENCE_TOTAL_CHARS - total
        if available <= 0:
            break
        text = text[:available]
        if not text:
            break
        result.append(text)
        seen.add(text)
        total += len(text)
        if len(result) >= MAX_EVIDENCE_ITEMS:
            break
    return tuple(result)


def _normalize_identifier(value: str, name: str, *, max_chars: int) -> str:
    value = _require_text(value, name).strip()
    if not value:
        raise ValueError(f"{name} cannot be empty")
    if len(value) > max_chars:
        raise ValueError(f"{name} cannot exceed {max_chars} characters")
    if _CONTROL_CHARS.search(value):
        raise ValueError(f"{name} contains control characters")
    if _clean_text(value, max_chars=max_chars) != value:
        raise ValueError(f"{name} contains unsafe path or credential data")
    return value


@dataclass(frozen=True)
class FailureMemoryRecord:
    """One project-scoped incident and its bounded validated evidence."""

    memory_id: str
    project_id: str
    task_id: str | None
    fingerprint: str
    kind: str
    summary: str
    action: str = ""
    affected_paths: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    status: FailureMemoryStatus = "open"
    occurrence_count: int = 1
    task_ids: tuple[str, ...] = ()
    first_seen_at: str = ""
    last_seen_at: str = ""
    resolved_at: str | None = None
    resolution_evidence: tuple[str, ...] = ()
    superseded_by: str | None = None

    def validate(self) -> None:
        _normalize_identifier(self.memory_id, "memory_id", max_chars=256)
        _normalize_identifier(self.project_id, "project_id", max_chars=MAX_PROJECT_ID_CHARS)
        if self.task_id is not None:
            _normalize_identifier(self.task_id, "task_id", max_chars=MAX_TASK_ID_CHARS)
        if not _HEX_64.fullmatch(self.fingerprint):
            raise ValueError("failure fingerprint must be a SHA-256 hex digest")
        _normalize_identifier(self.kind, "kind", max_chars=MAX_KIND_CHARS)
        summary = sanitize_failure_text(self.summary, max_chars=MAX_SUMMARY_CHARS)
        if not summary:
            raise ValueError("failure summary cannot be empty")
        if summary != self.summary:
            raise ValueError("failure summary must be normalized and redacted")
        action = sanitize_failure_text(self.action, max_chars=MAX_ACTION_CHARS)
        if action != self.action:
            raise ValueError("failure action must be normalized and redacted")
        if normalize_affected_paths(self.affected_paths) != self.affected_paths:
            raise ValueError("affected paths must be normalized and unique")
        if _normalize_evidence(self.evidence) != self.evidence:
            raise ValueError("failure evidence must be normalized and bounded")
        if self.status not in {"open", "resolved", "superseded"}:
            raise ValueError("unsupported failure memory status")
        if type(self.occurrence_count) is not int or self.occurrence_count < 1:
            raise ValueError("occurrence_count must be a positive integer")
        if len(self.task_ids) > MAX_TASK_IDS:
            raise ValueError("too many task ids in failure memory")
        for task_id in self.task_ids:
            _normalize_identifier(task_id, "task_id", max_chars=MAX_TASK_ID_CHARS)
        if self.task_id is not None and self.task_id not in self.task_ids:
            raise ValueError("task_id must be present in task_ids")
        _require_text(self.first_seen_at, "first_seen_at")
        _require_text(self.last_seen_at, "last_seen_at")
        if not self.first_seen_at.strip() or not self.last_seen_at.strip():
            raise ValueError("failure timestamps cannot be empty")
        if self.resolved_at is not None:
            _require_text(self.resolved_at, "resolved_at")
        if _normalize_evidence(self.resolution_evidence) != self.resolution_evidence:
            raise ValueError("resolution evidence must be normalized and bounded")
        if self.superseded_by is not None:
            _normalize_identifier(self.superseded_by, "superseded_by", max_chars=256)

    def compact_summary(self) -> dict[str, Any]:
        """Return the safe context shape suitable for prompts and UI state."""

        self.validate()
        return {
            "memory_id": self.memory_id,
            "project_id": self.project_id,
            "task_id": self.task_id,
            "fingerprint": self.fingerprint[:16],
            "kind": self.kind,
            "summary": self.summary,
            "action": self.action,
            "affected_paths": list(self.affected_paths),
            "status": self.status,
            "occurrence_count": self.occurrence_count,
            "first_seen_at": self.first_seen_at,
            "last_seen_at": self.last_seen_at,
        }

    def to_dict(self, *, include_evidence: bool = True) -> dict[str, Any]:
        self.validate()
        value = {
            **self.compact_summary(),
            "task_ids": list(self.task_ids),
            "resolved_at": self.resolved_at,
            "superseded_by": self.superseded_by,
        }
        if include_evidence:
            value["evidence"] = list(self.evidence)
            value["resolution_evidence"] = list(self.resolution_evidence)
        return value


def validate_verification_evidence(
    value: str | Mapping[str, Any] | Sequence[str] | None,
) -> tuple[str, ...]:
    """Validate and bound explicit evidence supplied to a resolve operation.

    A non-empty string/list is considered explicit because the caller had to
    pass it to this method.  Mapping inputs are stricter: a mapping that
    explicitly says ``verified: false`` or ``passed: false`` is rejected.
    """

    if value is None:
        raise ValueError("verified evidence is required to resolve a failure")
    if isinstance(value, Mapping):
        if not value:
            raise ValueError("verified evidence cannot be empty")
        for key in ("verified", "passed"):
            if key in value and value[key] is False:
                raise ValueError("verification evidence does not confirm success")
        status = value.get("status")
        if isinstance(status, str) and status.casefold() in {"failed", "error", "blocked"}:
            raise ValueError("verification evidence does not confirm success")
        pieces: list[str] = []
        for key in ("check", "command", "result", "summary", "evidence", "verification_id", "status"):
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                pieces.append(f"{key}: {item}")
        if not pieces:
            raise ValueError("verified evidence must contain a bounded result")
        return _normalize_evidence(pieces)
    if isinstance(value, str):
        if not value.strip():
            raise ValueError("verified evidence cannot be empty")
        return _normalize_evidence((value,))
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        result = _normalize_evidence(value)
        if not result:
            raise ValueError("verified evidence cannot be empty")
        return result
    raise TypeError("verified evidence must be text, a mapping, or a sequence")


__all__ = [
    "MAX_AFFECTED_PATHS",
    "MAX_CONTEXT_HINT_CHARS",
    "MAX_EVIDENCE_CHARS",
    "MAX_EVIDENCE_ITEMS",
    "MAX_EVIDENCE_TOTAL_CHARS",
    "MAX_MEMORY_ROWS_PER_PROJECT",
    "MAX_QUERY_LIMIT",
    "FailureMemoryRecord",
    "FailureMemoryStatus",
    "failure_fingerprint",
    "normalize_affected_paths",
    "normalize_failure_text",
    "normalize_relative_path",
    "normalize_supplied_fingerprint",
    "sanitize_failure_text",
    "validate_verification_evidence",
]
