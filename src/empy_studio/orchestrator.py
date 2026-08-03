from __future__ import annotations

from collections import defaultdict
from typing import Any

DOMAIN_MAP = {
    "landing": ("product", "ux", "frontend"),
    "dashboard": ("product", "ux", "frontend"),
    "login": ("ux", "frontend", "security"),
    "auth": ("backend", "security"),
    "payment": ("backend", "security", "integration"),
    "database": ("backend", "database"),
    "api": ("backend", "integration"),
    "release": ("qa", "release"),
    "rtl": ("frontend", "qa"),
    "responsive": ("frontend", "qa"),
    "ریسپانسیو": ("frontend", "qa"),
    "داشبورد": ("product", "ux", "frontend"),
    "لندینگ": ("product", "ux", "frontend"),
    "ورود": ("ux", "frontend", "security"),
}

AGENT_MAP = {
    "product": "Product Agent",
    "ux": "UX / Prototype Agent",
    "frontend": "Frontend Agent",
    "backend": "Backend Agent",
    "database": "Database Agent",
    "security": "Security Reviewer",
    "integration": "Integration Agent",
    "qa": "QA Agent",
    "release": "Release Integrator",
}


def detect_domains(text: str) -> list[str]:
    lowered = text.lower()
    domains: set[str] = set()
    for keyword, values in DOMAIN_MAP.items():
        if keyword in lowered:
            domains.update(values)
    if not domains:
        domains.update(["product", "backend"])
    domains.update(["qa", "release"])
    return sorted(domains)


def build_tasks(project: dict[str, Any], request: dict[str, Any]) -> list[dict[str, Any]]:
    del project  # reserved for future project-specific routing
    domains = detect_domains(request["text"])
    tasks: list[dict[str, Any]] = []
    previous: list[str] = []

    if "product" in domains or "ux" in domains:
        tasks.append({
            "id": "T01",
            "title": "Product and UX decision",
            "owner": "Product Agent",
            "read_scope": ["project identity", "active request", "approved decisions"],
            "write_scope": ["artifacts/product_decision.json"],
            "depends_on": [],
        })
        previous = ["T01"]

    if "ux" in domains:
        tasks.append({
            "id": f"T{len(tasks)+1:02d}",
            "title": "Visual direction and prototype",
            "owner": "UX / Prototype Agent",
            "read_scope": ["product decision", "brand constraints", "reference patterns"],
            "write_scope": ["artifacts/prototype/", "artifacts/design_decision.json"],
            "depends_on": previous.copy(),
        })
        previous = [tasks[-1]["id"]]

    implementers: list[str] = []
    write_scope = request.get("write_scope", {})
    for domain in ["frontend", "backend", "database", "integration"]:
        if domain in domains:
            task_id = f"T{len(tasks)+1:02d}"
            tasks.append({
                "id": task_id,
                "title": f"{domain.title()} implementation",
                "owner": AGENT_MAP[domain],
                "read_scope": ["approved plan", "assigned files", "contracts"],
                "write_scope": write_scope.get(domain, []),
                "depends_on": previous.copy(),
            })
            implementers.append(task_id)

    review_dependencies = implementers or previous.copy()
    if "security" in domains:
        task_id = f"T{len(tasks)+1:02d}"
        tasks.append({
            "id": task_id,
            "title": "Security review",
            "owner": "Security Reviewer",
            "read_scope": ["changed files", "security-sensitive contracts"],
            "write_scope": ["artifacts/handoffs/security.json"],
            "depends_on": review_dependencies,
        })
        review_dependencies = [task_id]

    qa_id = f"T{len(tasks)+1:02d}"
    tasks.append({
        "id": qa_id,
        "title": "QA and runtime verification",
        "owner": "QA Agent",
        "read_scope": ["complete diff", "test manifest"],
        "write_scope": ["artifacts/reports/qa.json"],
        "depends_on": review_dependencies,
    })
    tasks.append({
        "id": f"T{len(tasks)+1:02d}",
        "title": "Final synchronization and release",
        "owner": "Release Integrator",
        "read_scope": ["all handoffs", "complete project", "QA report"],
        "write_scope": ["artifacts/release/"],
        "depends_on": [qa_id],
    })
    return tasks


def validate_ownership(tasks: list[dict[str, Any]]) -> list[dict[str, str]]:
    owners: dict[str, str] = {}
    conflicts: list[dict[str, str]] = []
    for task in tasks:
        for path in task.get("write_scope", []):
            if path in owners and owners[path] != task["owner"]:
                conflicts.append({"path": path, "owners": f"{owners[path]} | {task['owner']}"})
            owners[path] = task["owner"]
    return conflicts


def schedule(tasks: list[dict[str, Any]]) -> list[list[str]]:
    indegree = {task["id"]: len(task["depends_on"]) for task in tasks}
    children: dict[str, list[str]] = defaultdict(list)
    for task in tasks:
        for dependency in task["depends_on"]:
            children[dependency].append(task["id"])

    waves: list[list[str]] = []
    ready = sorted(node for node, degree in indegree.items() if degree == 0)
    visited = 0
    while ready:
        wave = ready
        waves.append(wave)
        upcoming: list[str] = []
        for node in wave:
            visited += 1
            for child in children[node]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    upcoming.append(child)
        ready = sorted(upcoming)

    if visited != len(tasks):
        raise ValueError("Task graph contains a cycle")
    return waves


def create_plan(project: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    tasks = build_tasks(project, request)
    conflicts = validate_ownership(tasks)
    return {
        "engine": "empy_studio.orchestrator",
        "project_id": project["project_id"],
        "request_id": request["request_id"],
        "domains": detect_domains(request["text"]),
        "tasks": tasks,
        "waves": schedule(tasks),
        "ownership_conflicts": conflicts,
        "status": "blocked" if conflicts else "ready",
        "host_contract": "The agent host executes exact scopes and returns structured handoffs.",
    }
