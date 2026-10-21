"""Isolated synthetic UI fixture for S26C screenshots. Never touches var/ databases.
Usage: python prepare.py <target.sqlite3>"""
import json, secrets, sys
from datetime import timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, 'apps/tests')
from test_follow_up import FollowUpTests
from apps.compass import records, access, events, clinical_rules as rules, assessments
from apps.compass.db import connect

x = FollowUpTests('test_no_outcome_not_missed_no_plan_not_draft')
x.setUp()
try:
    today = records.today()
    x.entry(today.isoformat(), wellbeing='worse', complaints_status='known',
            complaints_text='Синтетическая жалоба: трудно засыпать', adverse_events_status='known',
            adverse_events_text='Вымышленная тошнота. Причина не установлена.',
            summary='Синтетический самоотчёт для проверки экранов.')
    x.entry((today - timedelta(days=3)).isoformat(), wellbeing='same', summary='Более ранний синтетический самоотчёт.')
    x.entry((today - timedelta(days=6)).isoformat(), 'doc-a', summary='Синтетический визит врача.')
    x.assessment()
    action = x.action(kind='plan_change')
    x.task(action, label='Обсудить самочувствие на повторном приёме (синтетика)')
    # second patient linked to doctor A
    access.accept_invite(x.db, 'pat-b', access.invite(x.db, 'doc-a', 'D02'))
    x.entry((today - timedelta(days=1)).isoformat(), 'pat-b') if False else None
    # pending assessment request for patient A
    f = assessments.definition()
    x.post('doc-a', '/patients/D01/assessment-requests', {'assignment_key': secrets.token_hex(16), 'form_version_id': f['id'],
        'age_status': 'known', 'age_years': '35', 'age_basis': 'Синтетический профиль'})
    rid = x.db.execute("SELECT id FROM assessment_requests ORDER BY requested_at DESC LIMIT 1").fetchone()[0]
    # critical signal from the safety form
    doc, pat = {'id': 'doc-a', 'role': 'doctor'}, {'id': 'pat-a', 'role': 'patient'}
    x.db.execute("UPDATE patients SET age_status='known',age_years=35 WHERE id='D01'")
    rules.save_context(x.db, doc, 'D01', {'request_key': secrets.token_hex(16), 'observed_on': today.isoformat(),
        'gad_status': 'present', 'severity': 'nonsevere', 'suicide_risk': 'denied', 'psychiatric_comorbidity': 'denied',
        'treatment_resistance': 'denied', 'aviandr_prescription': 'active', 'clinical_basis': 'Synthetic doctor record',
        'prescription_basis': 'Synthetic existing prescription'})
    form = {'request_key': secrets.token_hex(16), 'observed_on': today.isoformat(), 'safety_form_version': 'aviandr-safety-v1',
            **{'safety_' + f_: 'present' if f_ in ('taken', 'after_dose', 'current', 'rigidity') else 'denied' for f_ in rules.SAFETY_FIELDS}}
    records.save(x.db, pat, 'D01', 'self_report', form)
    while events.process_one(x.db):
        pass
    target = connect(sys.argv[1]); x.db.backup(target); target.close()
    Path(sys.argv[1] + '.json').write_text(json.dumps({'assessment_request': rid}))
finally:
    x.tearDown()
