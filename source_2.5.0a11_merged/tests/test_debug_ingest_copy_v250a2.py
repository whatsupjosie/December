from __future__ import annotations

from pathlib import Path

import pytest

from iteration_wallet.vault_v21 import VaultEngine, VaultError


def _vault(tmp_path: Path):
    vault = VaultEngine(tmp_path / 'wallet')
    project = vault.create_project('P')
    section = vault.create_section(project['id'], 'S')
    return vault, project, section


def test_ingest_refuses_symlink_source(tmp_path: Path):
    vault, project, section = _vault(tmp_path)
    target = tmp_path / 'target.txt'
    target.write_text('secret')
    link = tmp_path / 'link.txt'
    link.symlink_to(target)
    with pytest.raises(VaultError, match='symlink'):
        vault.add_raw_source(project['id'], section['id'], str(link))


def test_ingest_refuses_existing_destination_without_overwrite(tmp_path: Path, monkeypatch):
    vault, project, section = _vault(tmp_path)
    src = tmp_path / 'source.txt'
    src.write_text('new bytes')
    fixed_id = 'fixed-id'
    monkeypatch.setattr(vault, '_uid', lambda: fixed_id)
    destination_dir = vault._compartment_dir(project['id'], section['id'], 'raw_sources')
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / vault._safe_copy_name(fixed_id, src)
    destination.write_text('existing bytes')

    with pytest.raises(VaultError, match='already exists'):
        vault.add_raw_source(project['id'], section['id'], str(src))
    assert destination.read_text() == 'existing bytes'


def test_ingest_copies_exact_bytes_and_uses_private_mode(tmp_path: Path):
    vault, project, section = _vault(tmp_path)
    src = tmp_path / 'source.bin'
    payload = b'abc\x00def' * 4096
    src.write_bytes(payload)
    record = vault.add_candidate(project['id'], section['id'], str(src))
    destination = Path(record['vault_path'])
    assert destination.read_bytes() == payload
    assert destination.stat().st_mode & 0o077 == 0
