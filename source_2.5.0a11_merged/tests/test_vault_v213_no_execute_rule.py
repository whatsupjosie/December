import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from iteration_wallet.vault_v21 import VaultEngine, VaultError, NO_EXECUTE_RULE
import iteration_wallet.server as server


def _make_file(text: str = 'print("boom")', suffix: str = ".py") -> Path:
    handle = tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False)
    handle.write(text)
    handle.flush()
    handle.close()
    return Path(handle.name)


def _candidate(vault: VaultEngine):
    project = vault.create_project("No Execute Project")
    section = vault.create_section(project["id"], "Dangerous Candidate")
    src = _make_file('import os\nos.remove("everything")')
    try:
        candidate = vault.add_candidate(
            project["id"], section["id"], str(src), notes="malicious if run"
        )
    finally:
        src.unlink(missing_ok=True)
    return project, section, candidate


def test_no_execute_rule_constant_is_primary_product_law():
    assert "never executes" in NO_EXECUTE_RULE
    assert "traceable copy-export protocol" in NO_EXECUTE_RULE


def test_custodied_candidate_is_marked_non_executable_on_ingest():
    with tempfile.TemporaryDirectory() as tmpdir:
        vault = VaultEngine(Path(tmpdir))
        _, _, candidate = _candidate(vault)
        assert candidate["execution_allowed"] is False
        assert candidate["execution_policy"] == "never_execute_inside_iteration_wallet"


def test_no_execution_method_surface_exists():
    with tempfile.TemporaryDirectory() as tmpdir:
        vault = VaultEngine(Path(tmpdir))
        _candidate(vault)
        for method_name in ("run_file", "execute_file", "launch_file", "open_file"):
            assert not hasattr(vault, method_name)


def test_external_results_attach_without_running_candidate():
    with tempfile.TemporaryDirectory() as tmpdir:
        vault = VaultEngine(Path(tmpdir))
        project, section, candidate = _candidate(vault)
        result = vault.attach_external_test_results(
            project["id"], section["id"], candidate["id"],
            summary="External sandbox run passed 12/12 tests",
            passed=True,
            source="codex external sandbox",
            artifacts=["pytest-output.txt"],
        )
        assert result["observational_only"] is True
        assert result["passed"] is True
        refreshed = vault._find_file(project["id"], section["id"], candidate["id"])
        assert refreshed["external_test_results"][0]["source"] == "codex external sandbox"
        assert refreshed["execution_allowed"] is False


def test_export_is_unavailable_and_no_execution_surface_is_added():
    with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as outdir:
        vault = VaultEngine(Path(tmpdir))
        project, section, candidate = _candidate(vault)
        with pytest.raises(VaultError, match="not yet migrated"):
            vault.export_working_copy(
                project["id"], section["id"], candidate["id"], outdir,
                ceremony_token="no-token-can-exist", session_id="no-session",
            )
        assert list(Path(outdir).iterdir()) == []
        assert not hasattr(vault, "run_file")


def test_v21_api_refuses_execution_and_unimplemented_externalization_route_is_absent():
    with tempfile.TemporaryDirectory() as tmpdir:
        old = (server.blackbox21, server.vault21, server.human_access, server.promotion21)
        runtime = server.build_canonical_v21_runtime(Path(tmpdir))
        server.blackbox21, server.vault21, server.human_access, server.promotion21 = runtime
        try:
            with TestClient(server.app) as client:
                project = client.post("/api/v21/projects", json={"name": "API No Execute"}).json()
                section = client.post(
                    f"/api/v21/projects/{project['id']}/sections", json={"name": "Core"}
                ).json()
                src = _make_file('print("do not run")')
                try:
                    candidate = client.post(
                        f"/api/v21/projects/{project['id']}/sections/{section['id']}/candidates",
                        json={"path": str(src), "notes": "api candidate"},
                    ).json()
                finally:
                    src.unlink(missing_ok=True)

                run_response = client.post(
                    f"/api/v21/projects/{project['id']}/sections/{section['id']}/files/{candidate['id']}/run"
                )
                assert run_response.status_code in (404, 405)

                tokens_before = client.get("/api/v21/ceremony/tokens").json()["tokens"]
                externalization = client.post(
                    f"/api/v21/projects/{project['id']}/sections/{section['id']}/files/{candidate['id']}/release",
                    json={"ceremony_token": "none", "confirmation": "RELEASE"},
                )
                assert externalization.status_code == 404
                tokens_after = client.get("/api/v21/ceremony/tokens").json()["tokens"]
                assert tokens_after == tokens_before
                assert candidate["state"] == "candidate"
        finally:
            server.blackbox21, server.vault21, server.human_access, server.promotion21 = old
