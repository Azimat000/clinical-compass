#!/usr/bin/env python3
"""Main-agent audit: synthetic admission and preservation of baseline work."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from apps.tests.test_retrieval_packages import artificial_package,policy,build,save,AT,PackageTests
from apps.compass.retrieval_corpus import (CorpusError,digest,eligible_sources,
    indexable_cards,load_snapshot,publish_snapshot,sha)

def write(name,value):
    (ROOT/'evidence/S17J02A'/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')

def admission_audit():
    report={'fixture':'artificial only, no clinical or legal admission of new real sources','scenarios':{}}
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp);records=artificial_package(root,count=4);policy(root,['NEW'])
        registry,manifest,blobs=build(root)
        first,created=publish_snapshot(root/'store',manifest,blobs)
        assert created and len(indexable_cards(first,registry,AT,evidence_root=root)['cards'])==4
        report['scenarios']['registered_four_new_sources']={'status':'PASS','admitted':4,'version':manifest['corpus_version']}
        assert not publish_snapshot(root/'store',manifest,blobs)[1]
        report['scenarios']['repeat_without_duplicates']='PASS'
        old={p.name:sha(p.read_bytes()) for p in first.iterdir()}
        artificial_package(root,'NEXT',2);policy(root,['NEW','NEXT'])
        current,new,newblobs=build(root);assert len(new['sources'])==6
        report['scenarios']['combined_two_packages_six_sources']='PASS'
        with patch('apps.compass.retrieval_corpus.os.rename',side_effect=OSError('artificial write failure')):
            try:publish_snapshot(root/'store',new,newblobs)
            except OSError:pass
            else:raise AssertionError('fault not propagated')
        assert not (root/'store'/new['corpus_version']).exists()
        assert not list((root/'store').glob('.building-*'))
        report['scenarios']['atomic_failure_no_partial_release']='PASS'
        records[0]['rights']['status']='unknown'
        save(root,'data/retrieval/packages/NEW/registry.json',dict(schema_version=1,sources=records))
        current,new,newblobs=build(root)
        assert new['sources'][0]['disposition']=='quarantined' and records[0]['artifact_sha256'] not in newblobs
        assert 'NEW0' in eligible_sources(first,current,AT,evidence_root=root)['refused']
        report['scenarios']['unknown_rights_quarantine_and_immediate_revocation']='PASS'
        publish_snapshot(root/'store',new,newblobs)
        assert old=={p.name:sha(p.read_bytes()) for p in first.iterdir()}
        assert load_snapshot(first)==manifest
        report['scenarios']['previous_snapshot_byte_preservation']='PASS'
        report['previous_snapshot_hashes']=old
    probe=PackageTests();probe.setUp()
    try:
        _,previous,old,_=probe.publish()
        before={p.name:sha(p.read_bytes()) for p in old.iterdir()}
        item,_=probe.replacement()
        registry,updated,blobs=build(probe.root)
        assert len(registry['sources'])==4 and registry['sources'][1:]==probe.records[1:]
        assert registry['sources'][0]['artifact_sha256']==item['artifact_sha256']
        assert not list((probe.root/'data/retrieval/packages/REVISED').glob('*.pdf'))
        publish_snapshot(probe.root/'store',updated,blobs)
        assert before=={p.name:sha(p.read_bytes()) for p in old.iterdir()}
        report['scenarios']['explicit_reviewed_replacement_without_copying_full_original']='PASS'
        report['replacement']={'previous_version':previous['corpus_version'],'new_version':updated['corpus_version'],
            'unchanged_other_sources':3,'new_PDF_copies':0}
    finally:probe.doCleanups()
    write('admission-expansion.json',report)

def preservation_audit():
    baseline=json.loads((ROOT/'evidence/S17J02A/baseline.json').read_text())
    ownership=json.loads((ROOT/'evidence/S17J02A/ownership.json').read_text())
    owned=set(ownership['owned_files'])
    changed=[]
    for p,h in baseline['tracked'].items():
        path=ROOT/p
        assert path.is_file(), 'removed baseline '+p
        if sha(path.read_bytes())!=h:
            assert p in owned, 'unexpected tracked mutation '+p
            changed.append(p)
    for p,h in baseline['untracked'].items():
        assert (ROOT/p).is_file() and sha((ROOT/p).read_bytes())==h, 'pre-existing user change lost '+p
    state=json.loads((ROOT/'memory/STATE.json').read_text())
    before=json.loads(subprocess.check_output(['git','show',baseline['head']+':memory/STATE.json'],cwd=ROOT))
    for sid,entry in before['slices'].items():
        if sid!='S17J02A':assert state['slices'][sid]==entry,'slice changed '+sid
    coverage=json.loads((ROOT/'plan/coverage.json').read_text())
    oldcoverage=json.loads(subprocess.check_output(['git','show',baseline['head']+':plan/coverage.json'],cwd=ROOT))
    assert len(coverage['items'])==83
    assert sum(len(item['subchecks']) for item in coverage['items'])==160
    assert len(coverage['items'])==len(oldcoverage['items'])
    for old,new in zip(oldcoverage['items'],coverage['items']):
        assert {k:v for k,v in old.items() if k!='actual_evidence'}=={k:v for k,v in new.items() if k!='actual_evidence'}
        assert all(e in new['actual_evidence'] for e in old['actual_evidence'])
    oldplan=subprocess.check_output(['git','show',baseline['head']+':plan/S17J-production.md'],cwd=ROOT).decode()
    newplan=(ROOT/'plan/S17J-production.md').read_text()
    for line in oldplan.splitlines():
        if any(line.startswith('| '+g+' |') for g in ['G01','G02','G03','G04','G05','G06','G07','G08','G09']):assert line in newplan
    current_untracked=subprocess.check_output(['git','ls-files','--others','--exclude-standard','-z'],cwd=ROOT).decode().split('\0')
    for p in (x for x in current_untracked if x):
        assert p in baseline['untracked'] or p in owned or p.startswith('evidence/S17J02A/'),'unexpected new path '+p
    report=dict(status='PASS',baseline_head=baseline['head'],baseline_tracked_files=len(baseline['tracked']),
        pre_existing_untracked_files_preserved=len(baseline['untracked']),changed_preexisting_paths=sorted(changed),
        ownership='main agent only; read-only researcher; no mutating workers',
        preserved=['accepted J01/J02 and every other slice state','source-registry / all original PDF / all old snapshots',
                   'frozen J01 files and evaluator','83 requirements / 160 subchecks and old statuses/evidence',
                   'G01–G09 exact table rows','clinical rules and application routes','pre-existing synthetic cycle audit'])
    write('preservation.json',report)
    print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':
    admission_audit();preservation_audit()
