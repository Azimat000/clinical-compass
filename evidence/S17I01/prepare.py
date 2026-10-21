"""Isolated, synthetic UI fixture. Never touches the workspace database."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
sys.path.insert(0,'apps/tests')
from test_follow_up import FollowUpTests
from apps.compass import records
from apps.compass.db import connect
from datetime import timedelta
import secrets

x=FollowUpTests('test_no_outcome_not_missed_no_plan_not_draft');x.setUp()
try:
    day=records.today().isoformat()
    x.entry(day,wellbeing='worse',adverse_events_status='known',adverse_events_text='Вымышленная тошнота. Причина не установлена.',summary='Синтетический самоотчёт для проверки сводки.')
    x.entry(day,'doc-a',adverse_events_status='denied',risk_factors_status='conflicting',risk_factors_text='Синтетические источники расходятся',summary='Другая синтетическая запись на ту же дату. '+'Длинное русское описание для проверки переноса строк. '*40)
    x.entry((records.today()-timedelta(days=3)).isoformat(),summary='Более ранний синтетический самоотчёт.')
    x.assessment();x.assessment(incomplete=True)
    action=x.action(kind='plan_change')
    task,_=x.task(action,label='Обсудить самочувствие на повторном приёме (синтетика)')
    x.post('pat-a',x.url+'/report',{'task_id':task['id'],'request_key':secrets.token_hex(16),'outcome':'missed','reason':'Синтетический пропуск'})
    x.post('doc-a',x.url+'/report',{'task_id':task['id'],'request_key':secrets.token_hex(16),'outcome':'conflicting','reason':'Синтетическое расхождение двух сообщений'})
    x.task(action,label='Пункт без отметки (синтетика)')
    target=connect(sys.argv[1]);x.db.backup(target);target.close()
finally:x.tearDown()
