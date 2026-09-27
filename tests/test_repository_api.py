"""Real repository execution through HTTP; only the River boundary is replaced."""

from __future__ import annotations

import hashlib
import json
import platform
import shutil
import time

from fastapi.testclient import TestClient
import pytest

from reflex import repository_routes
from reflex.app import create_app


BROKEN = "def total(amount):\n    return amount * 2\n"
FIXED = "def total(amount):\n    return amount\n"
TESTS = "from logic import total\n\ndef test_total():\n    assert total(7) == 7\n"


class RepositoryProvider:
    configured = True
    base_model = "test-repository-model"

    def __init__(self):
        self.calls = []
        self.answer = FIXED

    async def repair(self, prompt, checkpoint=None):
        self.calls.append(prompt)
        return {
            "code": self.answer,
            "summary": "Preserve the input amount.",
            "model": self.base_model,
            "input_token_hash": hashlib.sha256(prompt.encode()).hexdigest(),
            "tokenizer_revision": "test-only",
            "generation": {"temperature": 0},
        }


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    root = tmp_path.resolve() / "repository"
    (root / "backend").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "backend" / "logic.py").write_text(BROKEN)
    (root / "tests" / "test_logic.py").write_text(TESTS)
    (root / "pyproject.toml").write_text('[tool.pytest.ini_options]\npythonpath = ["backend"]\n')
    monkeypatch.setattr(repository_routes, "ROOT", root)
    provider = RepositoryProvider()
    # Every TestClient has its own database. Never touch a live job ledger.
    app = create_app(str(tmp_path / "isolated-api.sqlite3"), provider=provider)
    with TestClient(app) as client:
        yield root, provider, client, app
    app.state.store.close()


@pytest.fixture
def seatbelt():
    if platform.system() != "Darwin" or not shutil.which("sandbox-exec"):
        pytest.skip("Repository execution requires macOS Seatbelt")


def inspect(client):
    response = client.post(
        "/api/repository/inspect",
        json={
            "relative_file": "backend/logic.py",
            "test_path": "tests/test_logic.py",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def finished(client, response):
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in {"completed", "failed", "interrupted"}:
            return job
        time.sleep(0.025)
    pytest.fail("Repository job did not settle in 15 seconds")


def test_inspection_persists_exact_source_and_hashes(workspace):
    root, provider, client, app = workspace
    case = inspect(client)
    assert case["source"] == BROKEN
    assert case["test_content"] == TESTS
    assert case["source_hash"] == hashlib.sha256(BROKEN.encode()).hexdigest()
    assert case["include_tests_allowed"] is True
    assert app.state.store.get("datasets", case["id"])["task_kind"] == "repository_case"
    state = client.get("/api/repository/state").json()
    assert state["cases"][0]["id"] == case["id"]
    assert state["jobs"] == []
    assert provider.calls == []


def test_reproduce_runs_real_tests_and_binds_exact_code(workspace, seatbelt):
    root, provider, client, _ = workspace
    case = inspect(client)
    report = client.post("/api/repository/reproduce", json={"case_id": case["id"]}).json()
    assert report["status"] == "failed", report
    assert report["passed"] == 0 and report["total"] == 1
    assert report["isolation"]["enforced"] is True
    assert report["code_hash"] == case["source_hash"]
    passing = client.post(
        "/api/repository/reproduce",
        json={
            "case_id": case["id"],
            "code": FIXED,
        },
    ).json()
    assert passing["status"] == "passed", passing
    assert passing["code_hash"] == hashlib.sha256(FIXED.encode()).hexdigest()
    assert (root / "backend" / "logic.py").read_text() == BROKEN
    assert provider.calls == []


def test_river_workflow_runs_original_and_candidate_downloads_patch(workspace, seatbelt):
    root, provider, client, _ = workspace
    case = inspect(client)
    job = finished(
        client,
        client.post(
            "/api/repository/run",
            json={
                "case_id": case["id"],
                "instruction": "Return the amount without duplicating it.",
            },
        ),
    )
    assert job["status"] == "completed", job
    result = client.get(f"/api/repository/repairs/{job['id']}").json()
    assert result["baseline_report"]["status"] == "failed"
    assert result["report"]["status"] == "passed"
    assert result["code"] == FIXED
    assert result["include_tests"] is False
    assert len(provider.calls) == 1
    context = json.loads(provider.calls[0].split("REPOSITORY WORKSPACE\n", 1)[1])
    assert context["source"] == BROKEN
    assert "test_source" not in context
    assert "assert total(7) == 7" not in provider.calls[0]
    patch = client.get(f"/api/repository/repairs/{job['id']}/patch")
    assert patch.status_code == 200
    assert "attachment" in patch.headers["content-disposition"]
    assert "--- a/backend/logic.py" in patch.text
    assert "+    return amount" in patch.text
    assert (root / "backend" / "logic.py").read_text() == BROKEN


def test_test_source_is_only_sent_when_explicitly_selected(workspace, seatbelt):
    _, provider, client, _ = workspace
    case = inspect(client)
    job = finished(
        client,
        client.post(
            "/api/repository/run",
            json={
                "case_id": case["id"],
                "instruction": "Fix the reported assertion.",
                "include_tests": True,
            },
        ),
    )
    assert job["status"] == "completed", job
    context = json.loads(provider.calls[0].split("REPOSITORY WORKSPACE\n", 1)[1])
    assert context["test_source"] == TESTS
    assert job["result"]["include_tests"] is True


def test_manual_candidate_requires_no_provider_and_preserves_failed_result(workspace, seatbelt):
    _, provider, client, _ = workspace
    provider.configured = False
    case = inspect(client)
    job = finished(
        client,
        client.post(
            "/api/repository/run",
            json={
                "case_id": case["id"],
                "instruction": "Verify a candidate.",
                "code": BROKEN,
            },
        ),
    )
    assert job["status"] == "completed", job
    assert job["result"]["report"]["status"] == "failed"
    assert job["result"]["origin"] == "manual"
    assert client.get(f"/api/repository/repairs/{job['id']}/patch").status_code == 409
    assert provider.calls == []


def test_snapshot_drift_stops_before_provider(workspace):
    root, provider, client, _ = workspace
    case = inspect(client)
    (root / "tests" / "test_logic.py").write_text(TESTS + "\n# changed\n")
    response = client.post("/api/repository/reproduce", json={"case_id": case["id"]})
    assert response.status_code == 409
    job = finished(
        client,
        client.post(
            "/api/repository/run",
            json={
                "case_id": case["id"],
                "instruction": "Fix it.",
            },
        ),
    )
    assert job["status"] == "failed"
    assert "changed since inspection" in job["error"]
    assert provider.calls == []


def test_passing_original_does_not_make_a_paid_request(workspace, seatbelt):
    root, provider, client, _ = workspace
    (root / "backend" / "logic.py").write_text(FIXED)
    case = inspect(client)
    job = finished(
        client,
        client.post(
            "/api/repository/run",
            json={
                "case_id": case["id"],
                "instruction": "Repair it.",
            },
        ),
    )
    assert job["status"] == "failed", job
    assert "already pass" in job["error"]
    assert provider.calls == []


def test_secret_test_fixtures_stay_local_but_run_exactly(workspace, seatbelt):
    root, provider, client, _ = workspace
    secret = "sk-" + "a" * 32
    content = TESTS + f'\nFAKE_CREDENTIAL = "{secret}"\n'
    (root / "tests" / "test_logic.py").write_text(content)
    case = inspect(client)
    assert case["test_content_redacted"] is True
    assert case["include_tests_allowed"] is False
    assert secret not in json.dumps(case)
    assert case["test_hash"] == hashlib.sha256(content.encode()).hexdigest()
    blocked = client.post(
        "/api/repository/run",
        json={
            "case_id": case["id"],
            "instruction": "Repair it.",
            "include_tests": True,
        },
    )
    assert blocked.status_code == 422
    report = client.post("/api/repository/reproduce", json={"case_id": case["id"]}).json()
    assert report["status"] == "failed", report
    assert provider.calls == []


def test_credentials_and_path_injection_rejected_before_execution(workspace):
    root, provider, client, _ = workspace
    invalid = client.post(
        "/api/repository/inspect",
        json={
            "relative_file": "../backend/logic.py",
            "test_path": "tests/test_logic.py",
        },
    )
    assert invalid.status_code == 422
    case = inspect(client)
    secret = "sk-" + "b" * 32
    for payload in (
        {"instruction": secret},
        {"instruction": "Run this", "code": f'credential = "{secret}"\n'},
        {"instruction": "Run this", "root": "/"},
    ):
        assert (
            client.post("/api/repository/run", json={"case_id": case["id"], **payload}).status_code
            == 422
        )
    (root / "backend" / "logic.py").write_text(f'credential = "{secret}"\n')
    assert (
        client.post(
            "/api/repository/inspect",
            json={
                "relative_file": "backend/logic.py",
                "test_path": "tests/test_logic.py",
            },
        ).status_code
        == 422
    )
    assert provider.calls == []


def test_missing_ids_and_incomplete_jobs_are_actionable(workspace):
    _, _, client, app = workspace
    assert client.post("/api/repository/reproduce", json={"case_id": "missing"}).status_code == 404
    assert client.get("/api/repository/repairs/missing").status_code == 404
    job = app.state.store.create_job("repository_repair", {})
    assert client.get(f"/api/repository/repairs/{job['id']}").status_code == 409
    assert client.get(f"/api/repository/repairs/{job['id']}/patch").status_code == 409
