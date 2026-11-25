from __future__ import annotations

import json
import zipfile
from pathlib import Path

from iteration_wallet.canonical_evidence import CanonicalEvidenceAdapter
from iteration_wallet.labcopy_transaction import LabCopyTransactionCoordinator
from iteration_wallet.notification_manager import ActorKind, NotificationManager
from iteration_wallet.vault_v21 import VaultEngine


def runtime(tmp_path: Path):
    root=tmp_path/'wallet'
    evidence=CanonicalEvidenceAdapter(root, session_id='narrow-labcopy')
    vault=VaultEngine(root, blackbox=evidence, strict_ceremony_tokens=True)
    humans=NotificationManager(root, blackbox=evidence)
    lab=LabCopyTransactionCoordinator(vault,evidence,humans)
    vault.labcopy_coordinator=lab
    project=vault.create_project('P')
    section=vault.create_section(project['id'],'S')
    identity=humans.issue_identity_session('josie',ActorKind.HUMAN,device_id='d',verified_methods=['human_ceremony'])
    vault.open_vault()
    src=tmp_path/'source.txt'; src.write_text('parent bytes\n')
    candidate=vault.add_candidate(project['id'],section['id'],str(src))
    outside=tmp_path/'outside'; outside.mkdir()
    proposal=lab.export_proposal(project_id=project['id'],section_id=section['id'],object_id=candidate['id'],output_root=outside,lab_policy='manual external work')
    token=vault.issue_ceremony_token(lab.EXPORT_ACTION,identity.session_id,actor_id='josie',project_id=project['id'],section_id=section['id'],object_id=candidate['id'],proposal_id=proposal['proposal_id'],proposal_hash=proposal['proposal_hash'])['ceremony_token']
    exported=lab.export(project_id=project['id'],section_id=section['id'],object_id=candidate['id'],proposal_id=proposal['proposal_id'],proposal_hash=proposal['proposal_hash'],ceremony_token=token,session_id=identity.session_id)
    return evidence,vault,humans,lab,project,section,identity,candidate,proposal,exported


def test_export_manifest_is_hmac_authenticated(tmp_path: Path):
    _,_,_,lab,_,_,_,candidate,proposal,_=runtime(tmp_path)
    package=Path(proposal['external_package_path'])
    with zipfile.ZipFile(package) as z:
        manifest=json.loads(z.read('manifest.json'))
    assert manifest['parent_sha256']==candidate['hash']
    assert manifest['parent_object_id']==candidate['id']
    assert manifest['export_timestamp']
    assert manifest['hmac_algorithm']=='HMAC-SHA256'
    assert len(manifest['hmac_sha256'])==64
    assert lab.registry.verify_manifest(manifest)['valid'] is True


def test_missing_manifest_becomes_unlinked_raw_source(tmp_path: Path):
    evidence,vault,_,lab,p,s,_,_,_,_=runtime(tmp_path)
    returned=tmp_path/'result.txt'; returned.write_text('changed\n')
    out=lab.classify_reentry(project_id=p['id'],section_id=s['id'],result_path=returned,allowed_root=tmp_path,manifest_path=None)
    assert out['disposition']=='unlinked_raw_source'
    assert out['result']['state']=='raw'
    assert out['result']['link_status']=='unlinked'
    assert evidence.verify_chain()['ok'] is True


def test_bad_hmac_becomes_unlinked_raw_source(tmp_path: Path):
    _,_,_,lab,p,s,_,_,proposal,_=runtime(tmp_path)
    package=Path(proposal['external_package_path'])
    with zipfile.ZipFile(package) as z:
        manifest=json.loads(z.read('manifest.json'))
    manifest['hmac_sha256']='0'*64
    bad=tmp_path/'manifest.json'; bad.write_text(json.dumps(manifest))
    returned=tmp_path/'result.txt'; returned.write_text('changed\n')
    out=lab.classify_reentry(project_id=p['id'],section_id=s['id'],result_path=returned,allowed_root=tmp_path,manifest_path=bad)
    assert out['disposition']=='unlinked_raw_source'
    assert out['result']['state']=='raw'


def test_identical_hash_is_noop(tmp_path: Path):
    _,vault,_,lab,p,s,_,candidate,proposal,_=runtime(tmp_path)
    package=Path(proposal['external_package_path'])
    returned=tmp_path/'same.txt'; returned.write_text('parent bytes\n')
    before=len(vault.get_section(p['id'],s['id'])['files'])
    out=lab.classify_reentry(project_id=p['id'],section_id=s['id'],result_path=returned,allowed_root=tmp_path,manifest_path=package)
    assert out['disposition']=='no_op_identical_hash'
    assert out['result']['id']==candidate['id']
    assert len(vault.get_section(p['id'],s['id'])['files'])==before


def test_valid_changed_return_admits_new_candidate_with_derived_hash(tmp_path: Path):
    evidence,vault,_,lab,p,s,identity,candidate,proposal,_=runtime(tmp_path)
    package=Path(proposal['external_package_path'])
    returned=tmp_path/'changed.txt'; returned.write_text('changed bytes\n')
    classified=lab.classify_reentry(project_id=p['id'],section_id=s['id'],result_path=returned,allowed_root=tmp_path,manifest_path=package)
    assert classified['disposition']=='candidate_pending_authorization'
    admission=classified['proposal']
    token=vault.issue_ceremony_token(lab.ADMIT_ACTION,identity.session_id,actor_id='josie',project_id=p['id'],section_id=s['id'],object_id=candidate['id'],proposal_id=admission['proposal_id'],proposal_hash=admission['proposal_hash'])['ceremony_token']
    result=lab.admit_result(lab_id=proposal['lab_id'],capsule_id=classified['capsule']['capsule_id'],proposal_id=admission['proposal_id'],proposal_hash=admission['proposal_hash'],ceremony_token=token,session_id=identity.session_id)
    created=result['result']
    assert created['state']=='candidate'
    assert created['derived_from_hash']==candidate['hash']
    assert created['id']!=candidate['id']
    assert evidence.verify_chain()['ok'] is True
