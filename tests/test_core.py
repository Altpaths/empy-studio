import sys
from pathlib import Path

from empy_studio.learning import merge
from empy_studio.orchestrator import create_plan
from empy_studio.verifier import verify


def test_orchestrator_builds_safe_graph():
    project = {"project_id": "demo"}
    request = {
        "request_id": "REQ-1",
        "text": "Create a responsive landing and login flow, then release it.",
        "write_scope": {"frontend": ["public/index.html", "public/login.html"]},
    }
    result = create_plan(project, request)
    assert result["status"] == "ready"
    assert result["ownership_conflicts"] == []
    assert result["tasks"][-1]["owner"] == "Release Integrator"


def test_learning_rejects_project_specific_claims():
    graph = {"version": 0, "patterns": []}
    sprint = {
        "project_id": "demo",
        "sprint_id": "S1",
        "lessons": [
            {"statement": "Prototype major UI changes first.", "scope": "global", "validated": True, "evidence_count": 2},
            {"statement": "The demo brand uses blue.", "scope": "project", "validated": True, "evidence_count": 1},
        ],
    }
    result = merge(graph, sprint)
    assert len(result["patterns"]) == 1
    assert len(result["rejected"]) == 1


def test_verifier_keeps_external_checks_pending(tmp_path):
    marker = tmp_path / "ok.txt"
    marker.write_text("ok")
    result = verify({
        "checks": [
            {"id": "marker", "type": "file", "path": str(marker)},
            {"id": "live", "type": "external", "reason": "Needs deployment"},
        ]
    })
    assert result["status"] == "release_candidate"
    assert result["pending"] == ["live"]


def test_project_vault_creates_snapshot_and_excludes_secrets(tmp_path: Path) -> None:
    from zipfile import ZipFile

    from empy_studio.vault import initialize_vault, vault_status

    project = tmp_path / "sample-project"
    project.mkdir()
    (project / "app.py").write_text("print('hello')\n", encoding="utf-8")
    (project / ".env").write_text("SECRET=do-not-copy\n", encoding="utf-8")
    cache = project / "__pycache__"
    cache.mkdir()
    (cache / "ignored.pyc").write_bytes(b"ignored")

    vault = tmp_path / "vault"
    result = initialize_vault(
        project_root=project,
        vault_root=vault,
        project_id="sample-project",
        project_name="Sample Project",
    )

    assert result["status"] == "ready"
    assert result["file_count"] == 1
    assert (vault / "vault.json").exists()
    assert (vault / "baseline" / "manifest.json").exists()
    assert (vault / "knowledge" / "PROJECT_IDENTITY.md").exists()

    with ZipFile(vault / "baseline" / "source.zip") as archive:
        assert archive.namelist() == ["app.py"]

    status = vault_status(vault)
    assert status["snapshot_sha256"]
    assert status["checks"]["source_snapshot"] is True


def test_project_vault_rejects_invalid_project_id(tmp_path: Path) -> None:
    import pytest

    from empy_studio.vault import initialize_vault

    project = tmp_path / "project"
    project.mkdir()
    with pytest.raises(ValueError):
        initialize_vault(
            project_root=project,
            vault_root=tmp_path / "vault",
            project_id="Bad Project ID",
            project_name="Bad",
        )


def test_context_builder_selects_relevant_files_within_budget(tmp_path: Path) -> None:
    import json

    from empy_studio.context import build_context
    from empy_studio.vault import initialize_vault

    project = tmp_path / "project"
    project.mkdir()
    (project / "login.py").write_text("def login():\n    return True\n", encoding="utf-8")
    (project / "payments.py").write_text("def charge():\n    return True\n", encoding="utf-8")
    (project / "README.md").write_text("sample project\n", encoding="utf-8")

    vault = tmp_path / "vault"
    initialize_vault(
        project_root=project,
        vault_root=vault,
        project_id="context-demo",
        project_name="Context Demo",
    )
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps({
            "request_id": "REQ-CONTEXT-1",
            "text": "Review the login flow",
            "agent": "security",
        }),
        encoding="utf-8",
    )

    output = tmp_path / "context-package"
    result = build_context(
        vault_root=vault,
        request_path=request,
        output_dir=output,
        max_bytes=4_096,
    )

    selected = [item["path"] for item in result["selected_files"]]
    assert "login.py" in selected
    assert (output / "files" / "login.py").exists()
    assert (output / "CONTEXT.md").exists()
    assert result["used_bytes"] <= 4_096
    assert result["estimated_tokens"] > 0


def test_context_builder_respects_explicit_files(tmp_path: Path) -> None:
    import json

    from empy_studio.context import build_context
    from empy_studio.vault import initialize_vault

    project = tmp_path / "project"
    project.mkdir()
    (project / "a.py").write_text("A = 1\n", encoding="utf-8")
    (project / "special.py").write_text("SPECIAL = 1\n", encoding="utf-8")
    vault = tmp_path / "vault"
    initialize_vault(
        project_root=project,
        vault_root=vault,
        project_id="explicit-demo",
        project_name="Explicit Demo",
    )
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"request_id": "R2", "text": "Unrelated task"}), encoding="utf-8")

    result = build_context(
        vault_root=vault,
        request_path=request,
        output_dir=tmp_path / "context",
        explicit_files=["special.py"],
    )
    assert result["selected_files"][0]["path"] == "special.py"
    assert result["selected_files"][0]["reason"] == "explicit"


def test_doctor_reports_python_and_repository(tmp_path: Path) -> None:
    from empy_studio.environment import doctor

    (tmp_path / ".git").mkdir()
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    result = doctor(tmp_path)
    checks = {item["id"]: item for item in result["checks"]}
    assert checks["python"]["status"] == "pass"
    assert checks["git_repository"]["status"] == "pass"
    assert result["health_score"] > 0


def test_bootstrap_dry_run_selects_commands(tmp_path: Path) -> None:
    from empy_studio.environment import bootstrap

    result = bootstrap(tmp_path, dry_run=True, python_executable=sys.executable)
    assert result["status"] == "planned"
    assert result["commands"][0][1:3] == ["-m", "venv"]
    assert result["commands"][-1][-1] == "."
