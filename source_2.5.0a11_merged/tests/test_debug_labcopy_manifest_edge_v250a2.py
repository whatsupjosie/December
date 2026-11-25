from __future__ import annotations

import json
import zipfile
from pathlib import Path

from iteration_wallet.canonical_evidence import CanonicalEvidenceAdapter
from iteration_wallet.labcopy_transaction import LabCopyTransactionCoordinator
from iteration_wallet.notification_manager import ActorKind, NotificationManager
from iteration_wallet.vault_v21 import VaultEngine


def _runtime(tmp_path: Path):
    root = tmp_path / 'wallet'
    evidence = CanonicalEvidenceAdapter(root, session_id='debug-edge')
    vault = VaultEngine(root, blackbox=evidence, strict_ceremony_tokens=True)
    humans = NotificationManager(root, blackbox=evidence)
    lab = LabCopyTransactionCoordinator(vault, evidence, humans)
    vault.labcopy_coordinator = lab
    project = vault.create_project('P')
    section = vault.create_section(project['id'], 'S')
    identity = humans.issue_identity_session(
        'josie', ActorKind.HUMAN, device_id='d', verified_methods=['human_ceremony']
    )
    vault.open_vault()
    src = tmp_path / 'source.txt'
    src.write_text('parent bytes\n')
    candidate = vault.add_candidate(project['id'], section['id'], str(src))
    outside = tmp_path / 'outside'
    outside.mkdir()
    proposal = lab.export_proposal(
        project_id=project['id'], section_id=section['id'], object_id=candidate['id'],
        output_root=outside, lab_policy='manual external work'
    )
    token = vault.issue_ceremony_token(
        lab.EXPORT_ACTION, identity.session_id, actor_id='josie',
        project_id=project['id'], section_id=section['id'], object_id=candidate['id'],
        proposal_id=proposal['proposal_id'], proposal_hash=proposal['proposal_hash']
    )['ceremony_token']
    lab.export(
        project_id=project['id'], section_id=section['id'], object_id=candidate['id'],
        proposal_id=proposal['proposal_id'], proposal_hash=proposal['proposal_hash'],
        ceremony_token=token, session_id=identity.session_id
    )
    return evidence, vault, lab, project, section, candidate, proposal


def test_valid_hmac_but_missing_lab_id_demotes_to_unlinked_raw(tmp_path: Path):
    evidence, vault, lab, project, section, _, proposal = _runtime(tmp_path)
    package = Path(proposal['external_package_path'])
    with zipfile.ZipFile(package) as archive:
        manifest = json.loads(archive.read('manifest.json'))
    manifest.pop('lab_id', None)
    # HMAC remains valid because the approved signature binds only the three required fields.
    assert lab.registry.verify_manifest(manifest)['valid'] is True
    manifest_path = tmp_path / 'manifest.json'
    manifest_path.write_text(json.dumps(manifest))
    returned = tmp_path / 'changed.txt'
    returned.write_text('changed bytes\n')

    result = lab.classify_reentry(
        project_id=project['id'], section_id=section['id'], result_path=returned,
        allowed_root=tmp_path, manifest_path=manifest_path
    )

    assert result['disposition'] == 'unlinked_raw_source'
    assert result['result']['state'] == 'raw'
    assert result['result']['link_failure_reason'] == 'manifest_export_mismatch'
    assert evidence.verify_chain()['ok'] is True


def test_concurrent_first_manifest_key_creation_converges(tmp_path: Path):
    from concurrent.futures import ThreadPoolExecutor
    from iteration_wallet.labcopy_transaction import LabCopyRegistry

    root = tmp_path / 'wallet'
    registries = [LabCopyRegistry(root) for _ in range(8)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda registry: registry._manifest_key(), registries))

    assert len({value for value in results}) == 1
    assert len(results[0]) == 32


def test_manifest_key_creation_loser_reloads_winner_key(tmp_path: Path, monkeypatch):
    import os
    from iteration_wallet.labcopy_transaction import LabCopyRegistry

    registry = LabCopyRegistry(tmp_path / 'wallet')
    winner_key = b'w' * 32
    original_open = os.open
    triggered = False

    def racing_open(path, flags, mode=0o777):
        nonlocal triggered
        if Path(path) == registry.hmac_key_path and flags & os.O_EXCL and not triggered:
            triggered = True
            fd = original_open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                os.write(fd, winner_key)
                os.fsync(fd)
            finally:
                os.close(fd)
            raise FileExistsError(path)
        return original_open(path, flags, mode)

    monkeypatch.setattr(os, 'open', racing_open)
    assert registry._manifest_key() == winner_key


def test_allowed_root_must_be_directory(tmp_path: Path):
    _, _, lab, project, section, _, _ = _runtime(tmp_path)
    result = tmp_path / 'result.txt'
    result.write_text('bytes')
    try:
        lab.classify_reentry(
            project_id=project['id'], section_id=section['id'], result_path=result,
            allowed_root=result, manifest_path=None
        )
    except Exception as exc:
        assert 'allowed_root must be a directory' in str(exc)
    else:
        raise AssertionError('file-valued allowed_root was accepted')


def test_oversized_manifest_demotes_to_raw_source(tmp_path: Path):
    _, _, lab, project, section, _, _ = _runtime(tmp_path)
    result = tmp_path / 'result.txt'
    result.write_text('changed')
    manifest = tmp_path / 'manifest.json'
    manifest.write_bytes(b'{' + b' ' * (lab.MAX_EXTERNAL_MANIFEST_BYTES + 1) + b'}')
    classified = lab.classify_reentry(
        project_id=project['id'], section_id=section['id'], result_path=result,
        allowed_root=tmp_path, manifest_path=manifest
    )
    assert classified['disposition'] == 'unlinked_raw_source'
    assert classified['result']['link_failure_reason'] == 'manifest_invalid'


def test_duplicate_zip_manifests_demote_to_raw_source(tmp_path: Path):
    import warnings
    _, _, lab, project, section, _, proposal = _runtime(tmp_path)
    original = Path(proposal['external_package_path'])
    duplicate = tmp_path / 'duplicate.iwlab'
    with zipfile.ZipFile(original) as src, zipfile.ZipFile(duplicate, 'w') as dst:
        for item in src.infolist():
            dst.writestr(item, src.read(item))
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            dst.writestr('manifest.json', src.read('manifest.json'))
    result = tmp_path / 'result.txt'
    result.write_text('changed')
    classified = lab.classify_reentry(
        project_id=project['id'], section_id=section['id'], result_path=result,
        allowed_root=tmp_path, manifest_path=duplicate
    )
    assert classified['disposition'] == 'unlinked_raw_source'
    assert classified['result']['link_failure_reason'] == 'manifest_invalid'


def test_manifest_key_refuses_group_or_world_readable_permissions(tmp_path: Path):
    import os
    import pytest
    from iteration_wallet.labcopy_transaction import LabCopyRegistry, LabCopyTransactionError

    if os.name == 'nt':
        pytest.skip('POSIX permission bits are not authoritative on Windows')
    registry = LabCopyRegistry(tmp_path / 'wallet')
    registry.hmac_key_path.write_bytes(b'k' * 32)
    registry.hmac_key_path.chmod(0o644)
    with pytest.raises(LabCopyTransactionError, match='permissions are too broad'):
        registry._manifest_key()
