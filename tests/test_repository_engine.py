"""Repository boundary tests; live checks invoke local pytest only, never River."""

from __future__ import annotations

import hashlib
import json
import platform
import shutil

import pytest

from reflex import repository_engine as engine


BROKEN = "def total(amount):\n    return amount * 2\n"
FIXED = "def total(amount):\n    return amount\n"
TESTS = "from logic import total\n\ndef test_total():\n    assert total(7) == 7\n"


@pytest.fixture
def repository(tmp_path):
    root = tmp_path.resolve()
    (root / "backend").mkdir()
    (root / "tests").mkdir()
    (root / "backend" / "logic.py").write_text(BROKEN)
    (root / "tests" / "test_logic.py").write_text(TESTS)
    (root / "pyproject.toml").write_text('[tool.pytest.ini_options]\npythonpath = ["backend"]\n')
    return root


def inspect(root):
    return engine.inspect_repository_case("backend/logic.py", "tests/test_logic.py", root=root)


@pytest.fixture
def require_seatbelt():
    if platform.system() != "Darwin" or not shutil.which("sandbox-exec"):
        pytest.skip("Live repository verification needs macOS Seatbelt")


def test_inspection_hashes_selected_files_and_excludes_private_paths(repository):
    (repository / ".env").write_text("RIVER_API_KEY=test-only-do-not-copy")
    (repository / "backend" / ".env.private").write_text("test-only-do-not-copy")
    (repository / "backend" / "data").mkdir()
    (repository / "backend" / "data" / "private.json").write_text("{}")
    case = inspect(repository)
    assert case["source"] == BROKEN
    assert case["test_content"] == TESTS
    assert case["source_hash"] == hashlib.sha256(BROKEN.encode()).hexdigest()
    assert case["test_hash"] == hashlib.sha256(TESTS.encode()).hexdigest()
    assert [item["path"] for item in case["snapshot_manifest"]] == [
        "backend/logic.py",
        "pyproject.toml",
        "tests/test_logic.py",
    ]
    assert "test-only-do-not-copy" not in json.dumps(case)


@pytest.mark.parametrize(
    "source,test",
    [
        ("../backend/logic.py", "tests/test_logic.py"),
        ("/backend/logic.py", "tests/test_logic.py"),
        ("backend/../backend/logic.py", "tests/test_logic.py"),
        ("backend/logic.py", "tests/test_logic.py::test_total"),
        ("backend/logic.py", "../tests/test_logic.py"),
        ("backend/logic.py;echo", "tests/test_logic.py"),
        ("backend\\logic.py", "tests/test_logic.py"),
    ],
)
def test_rejects_paths_and_test_selectors(repository, source, test):
    with pytest.raises(engine.RepositoryExecutionError):
        engine.inspect_repository_case(source, test, root=repository)


def test_rejects_source_symlinks(repository):
    (repository / "backend" / "alias.py").symlink_to(repository / "backend" / "logic.py")
    with pytest.raises(engine.RepositoryExecutionError, match="symlink"):
        engine.inspect_repository_case("backend/alias.py", "tests/test_logic.py", root=repository)


def test_rejects_symlinked_parent_directory(repository):
    (repository / "backend" / "alias").symlink_to(repository / "tests", target_is_directory=True)
    with pytest.raises(engine.RepositoryExecutionError, match="symlink"):
        inspect(repository)


def test_snapshot_drift_stops_before_any_process(repository, monkeypatch):
    case = inspect(repository)
    (repository / "tests" / "test_logic.py").write_text(TESTS + "\n# changed\n")
    monkeypatch.setattr(
        engine, "_invoke", lambda *args, **kwargs: pytest.fail("Must not execute stale input")
    )
    result = engine.run_repository_candidate(case, FIXED, root=repository)
    assert result["status"] == "error"
    assert "snapshot changed" in result["error"]
    assert result["exit_code"] is None


def test_case_cannot_choose_another_repository_root(repository, monkeypatch):
    case = inspect(repository)
    case["repository_root"] = "/"
    monkeypatch.setattr(
        engine, "_invoke", lambda *args, **kwargs: pytest.fail("Must not execute forged root")
    )
    result = engine.run_repository_candidate(case, FIXED, root=repository)
    assert result["status"] == "error"
    assert "explicitly selected root" in result["error"]


def test_missing_isolation_fails_closed_without_pytest(repository, monkeypatch):
    case = inspect(repository)
    monkeypatch.setattr(engine.platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        engine, "_invoke", lambda *args, **kwargs: pytest.fail("Must not execute without isolation")
    )
    result = engine.run_repository_candidate(case, FIXED, root=repository)
    assert result["status"] == "error"
    assert "no unisolated fallback" in result["error"]
    assert result["isolation"]["enforced"] is False
    assert not list((repository / ".cache" / "repository-runs").iterdir())


def test_failed_selfcheck_never_runs_pytest(repository, monkeypatch, require_seatbelt):
    calls = []

    def failed_probe(command, **kwargs):
        calls.append(command)
        return {"exit_code": 0, "stdout": '{"host_read_denied": true}', "stderr": "", "error": None}

    monkeypatch.setattr(engine, "_invoke", failed_probe)
    result = engine.run_repository_candidate(inspect(repository), FIXED, root=repository)
    assert result["status"] == "error"
    assert result["isolation"]["enforced"] is False
    assert len(calls) == 1
    assert (repository / "backend" / "logic.py").read_text() == BROKEN


def test_actual_pytest_failure_and_candidate_success_leave_original_unchanged(
    repository, require_seatbelt
):
    case = inspect(repository)
    before = {path: path.read_bytes() for path in repository.rglob("*") if path.is_file()}
    failure = engine.run_repository_candidate(case, BROKEN, root=repository)
    success = engine.run_repository_candidate(case, FIXED, root=repository)
    assert failure["isolation"]["enforced"] is True, failure
    assert failure["status"] == "failed", failure
    assert failure["exit_code"] == 1
    assert failure["passed"] == 0 and failure["total"] == 1
    assert success["status"] == "passed", success
    assert success["exit_code"] == 0
    assert success["passed"] == success["total"] == 1
    assert success["code_hash"] == hashlib.sha256(FIXED.encode()).hexdigest()
    assert "+    return amount" in success["diff"]
    assert success["snapshot_hash"] == case["snapshot_hash"]
    assert all(path.read_bytes() == content for path, content in before.items())
    assert not list((repository / ".cache" / "repository-runs").iterdir())


def test_candidate_has_no_inherited_credentials_and_cannot_write_snapshot(
    repository, monkeypatch, require_seatbelt
):
    monkeypatch.setenv("RIVER_API_KEY", "fixture-value-not-for-child")
    monkeypatch.setenv("REFLEX_INGEST_TOKEN", "fixture-value-not-for-child")
    content = """import os
from pathlib import Path
import pytest
from logic import total

def test_isolated_environment(tmp_path):
    assert "RIVER_API_KEY" not in os.environ
    assert "REFLEX_INGEST_TOKEN" not in os.environ
    assert total(7) == 7
    with pytest.raises(PermissionError):
        Path(__file__).write_text("changed")
    with pytest.raises(PermissionError):
        Path("/etc/passwd").read_text()
    (tmp_path / "permitted.txt").write_text("fixture")
"""
    (repository / "tests" / "test_logic.py").write_text(content)
    result = engine.run_repository_candidate(inspect(repository), FIXED, root=repository)
    assert result["status"] == "passed", result
    assert "fixture-value-not-for-child" not in json.dumps(result)
    assert (repository / "tests" / "test_logic.py").read_text() == content


def test_timeout_preserves_bounded_output_and_cleans_snapshot(
    repository, monkeypatch, require_seatbelt
):
    monkeypatch.setattr(engine, "MAX_SECONDS", 0.8)
    code = "def total(amount):\n    while True:\n        pass\n"
    result = engine.run_repository_candidate(inspect(repository), code, root=repository)
    assert result["status"] == "error", result
    assert "wall-time" in result["error"]
    assert (
        len(result["stdout"].encode()) + len(result["stderr"].encode()) <= engine.MAX_OUTPUT_BYTES
    )
    assert not list((repository / ".cache" / "repository-runs").iterdir())


def test_missing_pytest_report_cannot_be_success(tmp_path):
    with pytest.raises(engine.RepositoryExecutionError, match="success is unconfirmed"):
        engine._checks(tmp_path / "missing.xml")


def test_test_report_counts_failures_and_skips(tmp_path):
    path = tmp_path / "result.xml"
    path.write_text(
        '<testsuite><testcase name="pass"/><testcase name="skip"><skipped/></testcase>'
        '<testcase name="fail"><failure message="wrong result"/></testcase></testsuite>'
    )
    assert [item["status"] for item in engine._checks(path)] == ["passed", "skipped", "failed"]


def test_work_budget_does_not_follow_symlinks_and_rejects_large_files(tmp_path, monkeypatch):
    (tmp_path / "outside").symlink_to("/", target_is_directory=True)
    (tmp_path / "data.bin").write_bytes(b"12345")
    monkeypatch.setattr(engine, "MAX_WORK_BYTES", 4)
    with pytest.raises(engine.RepositoryExecutionError, match="work space exceeded"):
        engine._check_work_budget(tmp_path)
