import tempfile
from pathlib import Path

import pytest

from iteration_wallet.vault_v21 import VaultEngine, VaultError


def make_file(text: str = "data", suffix: str = ".txt") -> Path:
    handle = tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False)
    handle.write(text)
    handle.flush()
    handle.close()
    return Path(handle.name)


def setup_vault(tmpdir: str):
    vault = VaultEngine(Path(tmpdir))
    project = vault.create_project("App")
    section = vault.create_section(project["id"], "Core")
    return vault, project, section


def test_unimplemented_restoration_has_no_dormant_direct_method():
    """Restore is a precise product concept but has no bypass implementation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        vault, project, section = setup_vault(tmpdir)
        src = make_file("candidate")
        try:
            candidate = vault.add_candidate(project["id"], section["id"], str(src))
            before_path = candidate["vault_path"]
            before_state = candidate["state"]
            assert not hasattr(vault, "restore_file")
            assert candidate["state"] == before_state
            assert candidate["vault_path"] == before_path
            assert Path(before_path).is_file()
            assert vault.list_ceremony_tokens() == []
        finally:
            src.unlink(missing_ok=True)


def test_review_candidate_records_metadata_without_promoting():
    with tempfile.TemporaryDirectory() as tmpdir:
        vault, project, section = setup_vault(tmpdir)
        src = make_file("print('v2')", ".py")
        try:
            candidate = vault.add_candidate(project["id"], section["id"], str(src))
            review = vault.review_candidate(
                project["id"], section["id"], candidate["id"],
                verdict="needs_review",
                summary="Improves layout but needs tests",
                strengths=["clearer structure"],
                risks=["untested edge cases"],
            )
            assert review["verdict"] == "needs_review"
            assert candidate["state"] == "candidate"
            assert section["prime"] is None
            assert vault._find_file(project["id"], section["id"], candidate["id"])["last_review_verdict"] == "needs_review"
            metadata_dir = (
                Path(tmpdir) / "projects" / project["id"] / "sections" /
                section["id"] / "metadata" / "candidate_reviews"
            )
            assert list(metadata_dir.glob("*.json"))
        finally:
            src.unlink(missing_ok=True)


def test_review_rejects_invalid_verdict_and_non_candidate():
    with tempfile.TemporaryDirectory() as tmpdir:
        vault, project, section = setup_vault(tmpdir)
        src = make_file("raw")
        try:
            raw = vault.add_raw_source(project["id"], section["id"], str(src))
            with pytest.raises(VaultError, match="Only Candidates"):
                vault.review_candidate(project["id"], section["id"], raw["id"], "ready")
        finally:
            src.unlink(missing_ok=True)


def test_export_working_copy_is_unavailable_without_output_or_access_mutation():
    with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as outdir:
        vault, project, section = setup_vault(tmpdir)
        src = make_file("hello")
        try:
            candidate = vault.add_candidate(project["id"], section["id"], str(src))
            before_path = candidate["vault_path"]
            before_access = candidate["last_accessed_at"]
            with pytest.raises(VaultError, match="not yet migrated"):
                vault.export_working_copy(
                    project["id"], section["id"], candidate["id"], outdir,
                    ceremony_token="no-token-can-exist", session_id="no-session",
                )
            assert candidate["vault_path"] == before_path
            assert candidate["last_accessed_at"] == before_access
            assert Path(before_path).is_file()
            assert list(Path(outdir).iterdir()) == []
        finally:
            src.unlink(missing_ok=True)
