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
