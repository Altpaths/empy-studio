from __future__ import annotations

import hashlib
from typing import Any


def pattern_id(statement: str) -> str:
    digest = hashlib.sha1(statement.strip().lower().encode()).hexdigest()[:12].upper()
    return f"PAT-{digest}"


def merge(graph: dict[str, Any], sprint: dict[str, Any]) -> dict[str, Any]:
    patterns = {pattern["id"]: pattern for pattern in graph.get("patterns", [])}
    rejected: list[dict[str, str]] = []

    for lesson in sprint.get("lessons", []):
        if not lesson.get("validated") or lesson.get("evidence_count", 0) < 1:
            rejected.append({"statement": lesson["statement"], "reason": "unvalidated"})
            continue
        if lesson.get("scope") == "project":
            rejected.append({"statement": lesson["statement"], "reason": "project-specific"})
            continue

        identifier = pattern_id(lesson["statement"])
        if identifier not in patterns:
            patterns[identifier] = {
                "id": identifier,
                "statement": lesson["statement"],
                "scope": lesson["scope"],
                "confidence": 0,
                "validation_count": 0,
                "source_projects": [],
                "source_sprints": [],
                "tags": lesson.get("tags", []),
                "version": 0,
                "status": "candidate",
            }

        pattern = patterns[identifier]
        evidence = int(lesson.get("evidence_count", 1))
        pattern["validation_count"] += evidence
        pattern["confidence"] = min(100, pattern["confidence"] + 15 * evidence)
        if sprint["project_id"] not in pattern["source_projects"]:
            pattern["source_projects"].append(sprint["project_id"])
        if sprint["sprint_id"] not in pattern["source_sprints"]:
            pattern["source_sprints"].append(sprint["sprint_id"])
        pattern["version"] += 1

        if pattern["confidence"] >= 70 and len(pattern["source_projects"]) >= 2:
            pattern["status"] = "core"
        elif pattern["confidence"] >= 40:
            pattern["status"] = "validated"

    return {
        "version": graph.get("version", 0) + 1,
        "patterns": sorted(patterns.values(), key=lambda item: item["id"]),
        "rejected": rejected,
    }
