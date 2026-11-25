"""
Iteration Wallet v2.1 — Test Suite
===================================
Tests for Section/Candidate/Prime model with ceremony token enforcement.

Run:  pytest test_vault_v21.py -v
"""

import pytest
import tempfile
from pathlib import Path
from iteration_wallet.vault_v21 import VaultEngine, VaultError
from iteration_wallet.canonical_evidence import CanonicalEvidenceAdapter
from iteration_wallet.notification_manager import ActorKind, NotificationManager
from iteration_wallet.promotion_transaction import PromotionTransactionCoordinator


class TestSectionModel:
    """Test explicit Section/Candidate/Prime/Archive model."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Create a fresh vault for each test."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self.vault = VaultEngine(Path(tmpdir))
            yield

    def test_create_project(self):
        """Create a project."""
        result = self.vault.create_project("My App")
        assert result["name"] == "My App"
        assert result["id"]
        assert len(self.vault._state["projects"]) == 1

    def test_create_section(self):
        """Create a section in a project."""
        project = self.vault.create_project("My App")
        section = self.vault.create_section(project["id"], "Core Engine")
        assert section["name"] == "Core Engine"
        assert section["id"]

    def test_add_raw_source(self):
        """Add a file to Raw Sources."""
        project = self.vault.create_project("My App")
        section = self.vault.create_section(project["id"], "Data")

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("original data")
            f.flush()

            file_record = self.vault.add_raw_source(project["id"], section["id"], f.name)

            assert file_record["state"] == "raw"
            assert file_record["name"]
            assert file_record["hash"]
            assert len(self.vault.get_section(project["id"], section["id"])["files"]) == 1

            Path(f.name).unlink()

    def test_add_candidate(self):
        """Add a file to Candidates."""
        project = self.vault.create_project("My App")
        section = self.vault.create_section(project["id"], "Code")

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("print('hello')")
            f.flush()

            file_record = self.vault.add_candidate(
                project["id"], section["id"], f.name,
                notes="Attempt 1: simple version"
            )

            assert file_record["state"] == "candidate"
            assert file_record["notes"] == "Attempt 1: simple version"
            assert len(self.vault.get_section(project["id"], section["id"])["files"]) == 1

            Path(f.name).unlink()


class TestCeremonyTokens:
    """Active engine exposes no loose reusable authority token."""

    @pytest.fixture(autouse=True)
    def setup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.vault = VaultEngine(Path(tmpdir))
            self.project = self.vault.create_project("Test")
            self.section = self.vault.create_section(self.project["id"], "Test Section")
            yield

    def test_open_starts_session_without_general_authority_token(self):
        opened = self.vault.open_vault()
        assert opened["is_open"] is True
        assert opened["general_authority_token_issued"] is False
        assert "ceremony_token" not in opened
        self.vault.lock_vault()
        assert self.vault._is_open is False

    def test_unimplemented_retirement_has_no_dormant_direct_method(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("data")
            f.flush()
            record = self.vault.add_candidate(self.project["id"], self.section["id"], f.name)
        try:
            before_path = record["vault_path"]
            assert not hasattr(self.vault, "remove_file")
            assert not hasattr(self.vault, "release_from_custody")
            assert record["state"] == "candidate"
            assert record["vault_path"] == before_path
            assert Path(before_path).is_file()
        finally:
            Path(f.name).unlink(missing_ok=True)

    def test_no_delete_operation_surface(self):
        assert not hasattr(self.vault, "delete_file")


class TestPromotion:
    """Prime promotion is tested only through the canonical coordinator."""

    @pytest.fixture(autouse=True)
    def setup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.evidence = CanonicalEvidenceAdapter(root, session_id="vault-v21-tests")
            self.vault = VaultEngine(root, blackbox=self.evidence)
            self.humans = NotificationManager(root, blackbox=self.evidence)
            self.coordinator = PromotionTransactionCoordinator(
                self.vault, self.evidence, self.humans
            )
            self.project = self.vault.create_project("Test")
            self.section = self.vault.create_section(self.project["id"], "Test Section")
            self.identity = self.humans.issue_identity_session(
                "josie",
                ActorKind.HUMAN,
                verified_methods=["human_ceremony", "typing_challenge"],
            )
            self.vault.open_vault()
            with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
                f.write("print('v1')")
                f.flush()
                self.candidate1_path = f.name
            self.candidate1 = self.vault.add_candidate(
                self.project["id"], self.section["id"], self.candidate1_path, notes="Version 1"
            )
            yield
            Path(self.candidate1_path).unlink(missing_ok=True)

    def _promote(self, candidate: dict, reason: str) -> dict:
        issued = self.vault.issue_ceremony_token(
            "promote_candidate_to_prime",
            self.identity.session_id,
            actor_id=self.identity.actor_id,
            project_id=self.project["id"],
            section_id=self.section["id"],
            object_id=candidate["id"],
        )
        return self.coordinator.promote_to_prime(
            project_id=self.project["id"],
            section_id=self.section["id"],
            candidate_id=candidate["id"],
            ceremony_token=issued["ceremony_token"],
            session_id=self.identity.session_id,
            reason=reason,
        )

    def test_promote_candidate_to_prime(self):
        completed = self._promote(self.candidate1, "Stable version")
        result = completed["result"]
        assert result["state"] == "prime"
        assert result["promoted"]
        assert result["promotion_reason"] == "Stable version"
        assert self.vault.get_section(self.project["id"], self.section["id"])["prime"] == self.candidate1["id"]
        assert completed["verification"]["ok"] is True

    def test_promote_archives_old_prime(self):
        self._promote(self.candidate1, "First prime")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("print('v2')")
            f.flush()
            path2 = Path(f.name)
        try:
            candidate2 = self.vault.add_candidate(
                self.project["id"], self.section["id"], str(path2), notes="Version 2"
            )
            self._promote(candidate2, "Better version")
            assert self.candidate1["id"] in self.vault.get_section(self.project["id"], self.section["id"])["archive"]
            assert self.vault._find_file(self.project["id"], self.section["id"], self.candidate1["id"])["state"] == "archived"
            assert self.vault.get_section(self.project["id"], self.section["id"])["prime"] == candidate2["id"]
        finally:
            path2.unlink(missing_ok=True)

    def test_direct_engine_promotion_is_not_an_authority_path(self):
        with pytest.raises(VaultError, match="transaction coordinator"):
            self.vault.promote_to_prime(
                self.project["id"],
                self.section["id"],
                self.candidate1["id"],
                "not-authority",
                reason="Test",
            )


class TestSectionView:
    """Test section view that shows all compartments."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Create a section with files in different states."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self.vault = VaultEngine(Path(tmpdir))
            self.project = self.vault.create_project("Test")
            self.section = self.vault.create_section(self.project["id"], "Test Section")

            # Create raw source
            with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
                f.write("raw")
                f.flush()
                self.raw = self.vault.add_raw_source(self.project["id"], self.section["id"], f.name)
                Path(f.name).unlink()

            # Create candidate
            with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
                f.write("cand")
                f.flush()
                self.cand = self.vault.add_candidate(self.project["id"], self.section["id"], f.name)
                Path(f.name).unlink()

            yield

    def test_section_view_shows_all_compartments(self):
        """Section view displays every preserved compartment."""
        view = self.vault.get_section_view(self.project["id"], self.section["id"])

        assert "raw_sources" in view
        assert "candidates" in view
        assert "cradle" in view
        assert "archive" in view
        assert "retired" in view
        assert "recovery_holding" in view
        assert view["is_vault_open"] is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
