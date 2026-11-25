import json
import tempfile
from pathlib import Path

import pytest

from iteration_wallet.preservation import PERMANENT_PRESERVATION_RULE
from iteration_wallet.vault_v21 import VaultEngine, VaultError, PRESERVATION_RULE


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


def test_permanent_preservation_rule_is_primary_product_law():
    assert PRESERVATION_RULE == PERMANENT_PRESERVATION_RULE
    assert "remains preserved" in PRESERVATION_RULE
    assert "has no operation that reduces or discards protected content" in PRESERVATION_RULE


def test_no_destructive_public_method_exists_and_candidate_copy_is_preserved():
    with tempfile.TemporaryDirectory() as tmpdir:
        vault, project, section = setup_vault(tmpdir)
        src = make_file("candidate")
        try:
            candidate = vault.add_candidate(project["id"], section["id"], str(src))
            vault_copy = Path(candidate["vault_path"])
            for forbidden_name in ("delete_file", "remove_file", "release_from_custody"):
                assert not hasattr(vault, forbidden_name)
            assert vault_copy.is_file()
            assert candidate["state"] == "candidate"
        finally:
            src.unlink(missing_ok=True)


def test_unavailable_direct_custody_transition_fails_before_mutation():
    with tempfile.TemporaryDirectory() as tmpdir:
        vault, project, section = setup_vault(tmpdir)
        src = make_file("preserve me")
        try:
            candidate = vault.add_candidate(project["id"], section["id"], str(src))
            before_path = Path(candidate["vault_path"])
            before_state = candidate["state"]
            before_hash = candidate["hash"]
            with pytest.raises(VaultError, match="transaction coordinator"):
                vault.quarantine_file(
                    project["id"],
                    section["id"],
                    candidate["id"],
                    "no-token-can-exist",
                    session_id="no-session",
                    reason="suspicious output",
                )
            assert candidate["state"] == before_state
            assert candidate["vault_path"] == str(before_path)
            assert candidate["hash"] == before_hash
            assert before_path.is_file()
            assert vault.list_ceremony_tokens() == []
        finally:
            src.unlink(missing_ok=True)


def test_legacy_catalog_vocabulary_migration_is_additive_and_preserves_bytes(tmp_path: Path):
    vault = VaultEngine(tmp_path)
    project = vault.create_project("Legacy")
    section = vault.create_section(project["id"], "Core")
    source = tmp_path / "legacy-source.txt"
    source.write_text("preserved legacy bytes", encoding="utf-8")
    candidate = vault.add_candidate(project["id"], section["id"], str(source))
    custody_path = Path(candidate["vault_path"])
    original_bytes = custody_path.read_bytes()
    original_hash = candidate["hash"]

    state_path = tmp_path / "state_v21.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["projects"][0]["sections"][0]["files"][0]["state"] = "removed"
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    migrated = VaultEngine(tmp_path)
    record = migrated._find_file(project["id"], section["id"], candidate["id"])
    assert record["state"] == "retired"
    assert record["legacy_state"] == "removed"
    assert record["vault_path"] == str(custody_path)
    assert record["hash"] == original_hash
    assert custody_path.read_bytes() == original_bytes
    assert migrated.get_state()["preservation_migrations"][-1]["physical_paths_changed"] is False
    assert migrated.get_state()["preservation_migrations"][-1]["content_bytes_changed"] is False
