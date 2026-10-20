"""Literal extraction v2. Evidence candidates only, never clinical decisions.

Scopes are computed once, independent of the number of candidates. All offsets
refer to the unchanged input. Unknown language remains visible for human review.
"""
from bisect import bisect_right
from datetime import date
import json
import re

MONTHS = dict(zip(('января февраля марта апреля мая июня июля августа сентября октября ноября декабря').split(), range(1, 13)))
DATE_PATTERN = r'\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}[./]\d{1,2}[./](?:\d{4}|\d{2})|\d{1,2}\s+(?:' + '|'.join(MONTHS) + r')\s+\d{4}(?:\s+года)?)\b'
HISTORY = r'в\s+\d{1,3}\s+(?:лет|года?)\s+(?:отмечал|был[аи]?|страдал|перен[её]с|сообщал|принимал)|ранее|раньше|в прошлом|архив|стар(?:ой|ый|ом|ое|ого)|прежн(?:ей|ий)|до этого|вчера|до начала|в тот день|в выписке за прошл\w* год|в подростковом возрасте'
THIRD = r'сосед|подруг|друг(?:а|е|у)?\b|мат(?:ь|ери)|отец|отца|сестр\w*|брат\w*|сопровождающ\w*|бабушк\w*|дедушк\w*|о другом|не у меня'
UNCERTAIN = r'неизвест|не заполн|не указан|не описан|не помн|не ответ|нет сведений|нет подтверждения|не уверен|оставлен\w* пуст|не сообщает|не собран|не перечислен|список отсутствует|не подтвержд|не выясн|не провер|ничего не зна|данных нет|сведений нет|без ответа'
NEGATIVE = r'(?<!не )отрица\w*|не\s+(?:принима\w*|назнача\w*|начина\w*|упомина\w*|подтвержд\w*)|(?:^|[\s:«])нет\b|не было|не жалуется|отсутству(?:ет|ют)'


def parse_date(raw):
    parts = raw.lower().split()
    try:
        if len(parts) >= 3 and parts[1] in MONTHS:
            d, mo, y = int(parts[0]), MONTHS[parts[1]], int(parts[2])
        else:
            ns = re.split(r'[./-]', raw)
            if len(ns[0]) == 4:
                y, mo, d = map(int, ns)
            else:
                d, mo, y = map(int, ns)
                # Explicit bounded convention for short years, never infer century.
                if len(ns[2]) == 2:
                    y += 2000
        return 'present', date(y, mo, d).isoformat()
    except (ValueError, IndexError):
        return 'invalid', None


class Scopes:
    def __init__(self, text):
        self.text = text
        # A period is a boundary except inside decimal numbers/dates/ICD codes.
        self.breaks = [0] + [m.end() for m in re.finditer(r'[;\n\u2028\u2029!?]|\.(?=\s|$)', text)]
        self.breaks.append(len(text))

    def bounds(self, start, end):
        i = max(0, bisect_right(self.breaks, start) - 1)
        right = self.breaks[min(i + 1, len(self.breaks) - 1)]
        # A candidate ending in punctuation (e.g. л.) still belongs to its scope.
        return self.breaks[i], max(end, right)

    def context(self, start, end, local=False):
        a, b = self.bounds(start, end)
        if local:
            left = list(re.finditer(r',|\b(?:но|а|зато|однако)\b', self.text[a:start], re.I))
            right = re.search(r',|\b(?:но|а|зато|однако)\b', self.text[end:b], re.I)
            if left:
                a += left[-1].end()
            if right:
                b = end + right.start()
        # Bounded context prevents quadratic scans in long unpunctuated input.
        return self.text[max(a,start-240):min(b,end+240)].lower()

    def third_party(self, start, end):
        local=self.context(start,end,True)
        full=self.context(start,end)
        # A relative can be the reporter while the patient is the subject.
        own=r'у пациент(?:а|ки)\b|сам(?:ой|ого) пациент\w*|ответ пациента|пациент(?:ка)?\s+(?:принимает|жалуется|отмечает)'
        owns=list(re.finditer(own,local));others=list(re.finditer(THIRD,local))
        if owns and not re.search(r'не пациент',local):
            return bool(others and others[-1].start()>owns[-1].start())
        if re.search(THIRD,local):return True
        # Quoted first-person speech belongs to its explicitly named speaker.
        return bool(re.search(THIRD,full) and re.search(r'говорит|отвечал|не пациент',full))

    def uncertain(self, start, end):
        local=self.context(start,end,True)
        full=self.context(start,end)
        a,_=self.bounds(start,end)
        before=self.text[max(a,start-240):start].lower()
        local=re.sub(r'(?:после|на фоне)\s+неизвестн\w*\s+(?:таблетк\w*|лекарств\w*|препарат\w*)','',local)
        if re.search(UNCERTAIN,local) or re.search(r'не исключ|не отрица|возможно|вероятно|могла? быть|могло быть|может быть',local):return True
        if re.search(r'(?:сведен|информац|данн).{0,55}(?:нет|отсутств)',local):return True
        # A leading uncertainty governs its subordinate clause across a comma.
        if re.search(r'(?:неизвестно|нет сведений|нет подтверждения|не уверен|неясно|возможно|вероятно),?\s*(?:есть ли|есть|сейчас|что|принимает ли|пациент|принимает)',before):return True
        return False

    def state(self, start, end):
        c = self.context(start, end)
        local = self.context(start, end, True)
        before = self.text[max(self.bounds(start, end)[0], start - 75):start].lower()
        after = self.text[end:min(self.bounds(start, end)[1], end + 70)].lower()
        if re.search(r'переч[её]ркнут|(?:проект|предлаг\w*).{0,65}(?:отмен|не назначен|отклон)|назначения не было', c):
            return 'cancelled_proposal'
        if self.third_party(start,end):
            return 'third_party'
        if self.uncertain(start,end):
            return 'unknown'
        if re.search(r'(?<!не )отмен[её]н', local):
            return 'stopped'
        if re.search(r'обсуждал\w* ранее|ранее обсуждал', c):
            return 'historical'
        if re.search(r'подозрев|подозрен|требует\w* уточнен|уточнени', c):
            return 'suspected'
        if re.search(r'обсудить|планиру\w*.{0,60}обсуд|обсуд.{0,60}планиру',c):
            return 'considered'
        if re.search(NEGATIVE, local):
            return 'negated'
        if re.search(r'обсужд|рассмотр|рассматр|вопрос|предложен', c):
            return 'considered'
        if re.search(r'до этого|в прошлом|архив|старой|старый',c):
            return 'historical'
        if re.search(r'принял|принимал|пропустил|отмечен.{0,30}при[её]м', c):
            return 'patient_reported'
        if re.search(HISTORY, c):
            return 'historical'
        if '?' in c:
            return 'unknown'
        if re.search(r'со слов|по словам|самоотч[её]т|пациент|сообщ|принял|принимает|принимал', c):
            return 'patient_reported'
        return 'listed'


def extract_literals(text, fields, version, warning):
    scopes = Scopes(text)
    candidates = []
    identities = set()

    def add(field, assertion, value, start, end):
        identity = field, assertion, json.dumps(value, ensure_ascii=False, sort_keys=True), start, end
        if identity not in identities:
            identities.add(identity)
            candidates.append({'field': field, 'assertion': assertion, 'value': value,
                               'quote': text[start:end], 'span': {'start': start, 'end': end}})

    def scan(pattern, field, transform, group=0):
        for m in re.finditer(pattern, text, re.I):
            assertion, value = transform(m)
            a, b = m.span(group)
            add(field, assertion, value, a, b)

    def fixed(assertion, value):
        return lambda m: (assertion, value)

    def age(m):
        c=scopes.context(m.start(),m.end(),True)
        if int(m[1])>120 or re.search(r'вписано ошибочно|указан.{0,20}ошибочно',c):return 'invalid',None
        if scopes.third_party(m.start(),m.end()):return 'third_party',int(m[1])
        if re.search(HISTORY,c):return 'historical',int(m[1])
        return 'present',int(m[1])
    scan(r'\b(\d{1,3})\s*(?:лет\b|год(?:а)?\b|л\.)(?!\w)', 'age_years', age)
    scan(r'возраст\s*[:—-]?\s*(?:неизвестен|не заполнен|не указан)', 'age_years', fixed('unknown', None))
    scan(r'сколько лет\?\s*[—–-]\s*(\d{1,3})', 'age_years', lambda m: ('present' if int(m[1]) <= 120 else 'invalid', int(m[1]) if int(m[1]) <= 120 else None))

    scan(r'сведения о возрасте отсутствуют', 'age_years', fixed('unknown',None))

    for m in re.finditer(DATE_PATTERN, text, re.I):
        a, b = scopes.bounds(m.start(), m.end())
        before = text[a:m.start()].lower()
        field = 'received_date' if re.search(r'получен\w*\s*$', before) else 'medication_start' if re.search(r'начал\w*.{0,25}$|(?:при[её]м|принима\w*|назначени\w*).{0,50}\bс\s*$', before) else 'event_date'
        planned=bool(re.search(r'намечен|запланирован|состоится|предстоит',before))
        add(field, *(('not_due',None) if planned else parse_date(m[0])), m.start(), m.end())

    def diagnosis(m):
        state = scopes.state(m.start(), m.end())
        if state=='considered' or text[m.end():m.end()+1]=='?':state='suspected'
        return state if state in ('historical', 'suspected', 'unknown', 'negated', 'third_party') else 'present', m[0].upper() if re.fullmatch(r'f\d{2}(?:\.\d{1,2})?', m[0], re.I) else m[0].lower() if len(m[0]) > 3 else m[0].upper()
    scan(r'\b[Ff]\d{2}(?:\.\d{1,2})?\b', 'diagnosis', diagnosis)
    for m in re.finditer(r'\b(?:ГТР|генерализованное тревожное расстройство|депрессивный эпизод)\b', text, re.I):
        if not re.search(r'\bf\d{2}', scopes.context(m.start(), m.end())):
            add('diagnosis', *diagnosis(m), m.start(), m.end())
    scan(r'(?:диагноз(?:а)?\s+(?:не установлен|отсутствует|не вписан|не ставили|нет)|без установленного диагноза|врачебного диагноза нет)', 'diagnosis', fixed('unknown', None))
    scan(r'панические приступы(?=.{0,40}уточнен)', 'diagnosis_text', fixed('suspected', 'панические приступы'))

    meds = []
    for m in re.finditer(r'\b(?:Авиандр(?:а|ом|у|е)?|препарат\s+[A-Z])\b', text, re.I):
        state = scopes.state(m.start(), m.end())
        value = 'Авиандр' if m[0].lower().startswith('авиандр') else 'препарат ' + m[0][-1].upper()
        meds.append((m, state, value))
        add('medication', state, None if state == 'unknown' else value, m.start(), m.end())

    def dose_state(m):
        s = scopes.state(m.start(), m.end())
        return s if s in ('historical', 'cancelled_proposal', 'third_party', 'negated', 'considered', 'unknown', 'stopped') else 'present'
    for m in re.finditer(r'(?<![\w/])([-−]?\d{1,8}(?:[.,]\d{1,8})?)(?:\s*/\s*(\d{1,8}))?\s*(мг\b|мл\b|г\b|таблет\w*\b|таб\.)', text, re.I):
        unit = m[3].lower()
        value = float(m[1].replace(',', '.').replace('−','-'))
        if value < 0:
            add('dose','invalid',None,m.start(),m.end());continue
        if m[2]:
            if int(m[2]) == 0:
                add('dose', 'invalid', None, m.start(), m.end()); continue
            value /= int(m[2])
        value = int(value) if value.is_integer() else value
        unit = {'мг':'mg', 'г':'g', 'мл':'ml'}.get(unit, 'tablet')
        s = dose_state(m)
        add('dose', s, None if s == 'unknown' else {'value': value, 'unit': unit}, m.start(), m.end())
    scan(r'[«\"]?по\s*(\d{1,8})[»\"]?\s*,?\s*единица (?:измерения )?не (?:вписана|указана)', 'dose', lambda m:('incomplete',{'value':int(m[1]),'unit':None}))
    scan(r'доз[ауы]\s*(?:не помнит|неизвестна|не указан[аы]?|не написал)', 'dose', fixed('unknown', None))
    scan(r'\b(\d{1,8}(?:[.,]\d{1,8})?)\s+без единицы', 'dose', lambda m: ('incomplete', {'value':int(m[1]) if m[1].isdigit() else float(m[1].replace(',', '.')), 'unit':None}))
    scan(r'\b(\d{1,3})\s*раз(?:а)?\s*(?:в сутки|в день|/сут)', 'frequency_per_day', lambda m: (dose_state(m), int(m[1])))
    for pattern, n in [(r'один раз в день|однократно в сутки',1), (r'дважды (?:в день|в сутки)|два раза (?:в день|в сутки)',2), (r'трижды в день|три раза в день',3)]:
        scan(pattern, 'frequency_per_day', lambda m,n=n:(dose_state(m),n))
    scan(r'кратность\s*[:—–-]?\s*(?:не указана|неизвестна)', 'frequency_per_day', fixed('unknown', None))
    scan(r'(?:продолжает ли (?:терапию|при[её]м).{0,30}неизвестно|не уверен.{0,30}принимает|при[её]м не подтвержд[её]н)', 'medication_use', fixed('unknown', None))
    scan(r'(?<!не )не начинал\b', 'medication_use', fixed('negated', False))

    # Independent risk objects use local scopes: an unknown allergen does not
    # erase an explicitly present allergy, nor negate the next risk object.
    risk_patterns = {
        'medication_allergy': r'о своей аллергии|лекарственн\w* аллерги\w*|аллерги\w*\s+на лекарств\w*|сведения об аллергии|аллергологический анамнез',
        'pregnancy_status': r'беременн(?:ость|ости|а|ая)',
        'lactation_status': r'грудно(?:м|е) вскармливани[еи]|кормление грудью|лактаци[яиюей]\b',
    }
    for field, pattern in risk_patterns.items():
        for m in re.finditer(pattern, text, re.I):
            c = scopes.context(m.start(), m.end(), True)
            if re.search(r'противореч', c):
                a,b = scopes.bounds(m.start(),m.end())
                quotes=list(re.finditer(r'«(да|нет)»', text[m.end():b],re.I))
                for q in quotes:
                    add(field,'conflicting',q[1].lower()=='да',m.end()+q.start(),m.end()+q.end())
                if not quotes:add(field,'conflicting',None,m.start(),m.end())
            elif '?' in c or scopes.uncertain(m.start(),m.end()) or re.search(r'(?:сведен|информац|результат).{0,40}отсутств',c):s,v='unknown',None
            elif re.search(r'не беремен|не кормит|отрица|исключен|прекращен|\bнет\b',c) and not re.search(r'не отрица',c):s,v='negated',False
            elif re.search(r'подтвержд|\bда\b|\bесть\b|имеется|беременна',c):s,v=('patient_reported' if re.search(r'со слов|по словам',c) else 'present'),True
            else:s,v='unknown',None
            if not re.search(r'противореч',c):
                if scopes.third_party(m.start(),m.end()):s='third_party'
                _,end=scopes.bounds(m.start(),m.end())
                comma=re.search(',',text[m.end():end])
                if comma:end=m.end()+comma.start()
                add(field,s,v,m.start(),min(end,m.start()+2000))
    scan(r'название (?:лекарства|препарата) (?:не помнит|неизвестно|не указано)', 'medication_name', fixed('unknown',None))
    scan(r'принимаемые лекарства\s*:\s*неизвестно', 'concomitant_medications', fixed('unknown',None))
    scan(r'сила таблетки неизвестна|концентрация не записана', 'tablet_strength', fixed('unknown', None))
    scan(r'(?:дат[ау] начала (?:лечения|при[её]ма) не помнит|начало (?:при[её]ма )?(?:неизвестно|не помнит))', 'medication_start', fixed('unknown', None))
    scan(r'препарат не помнит', 'allergen', fixed('unknown', None))

    symptoms = [
        (r'сердцебиени\w*','сердцебиение'),(r'бессонниц\w*|сплю хуже','нарушение сна'),
        (r'подавленн\w* настроени\w*','сниженное настроение'),(r'усталост\w*','усталость'),
        (r'тошнот\w*','тошнота'),(r'сып[ьи]\b','сыпь'),(r'от[её]к\w* губ','отёк губ'),
        (r'головокружени\w*','головокружение'),(r'падени\w*','падение'),
        (r'потер[яюи] интереса','потеря интереса'),(r'слабост\w*','слабость'),
        (r'беспокойств\w*','беспокойство'),
    ]
    for pattern, value in symptoms:
        for m in re.finditer(pattern,text,re.I):
            c=scopes.context(m.start(),m.end(),True)
            full=scopes.context(m.start(),m.end())
            reversed_negation=bool(re.search(r'(?:неверно|неправда),?\s+что\s+'+re.escape(m[0][:4].lower())+r'\w*\s+(?:нет|отсутств)',full))
            state='unknown' if '?' in c or scopes.uncertain(m.start(),m.end()) and 'не отрица' not in c else 'historical' if re.search(HISTORY,c) else 'third_party' if scopes.third_party(m.start(),m.end()) else 'present' if reversed_negation else 'negated' if re.search(NEGATIVE,c) else 'present'
            add('symptom',state,None if state=='unknown' else value,m.start(),m.end())
    for field,pattern in [('anxiety',r'тревог[аиу]\b'),('dizziness',r'головокружени\w*'),('nausea',r'тошнот\w*'),('itch',r'зуд\w*'),('dyspnea',r'затруднени\w* дыхания|одышк\w*')]:
        for m in re.finditer(pattern,text,re.I):
            c=scopes.context(m.start(),m.end(),True)
            negative=bool(re.search(NEGATIVE,c)) and 'не отрица' not in c
            s='unknown' if '?' in c or scopes.uncertain(m.start(),m.end()) and 'не отрица' not in c else 'historical' if re.search(HISTORY,c) else 'negated' if negative else 'present'
            value=None if s=='unknown' else not negative
            if scopes.third_party(m.start(),m.end()):s='third_party'
            add(field,s,value,m.start(),m.end())

    # Literal reports of speech, no triage, severity, risk score or alert.
    for m in re.finditer(r'причин(?:ить|ении) себе вред[а]?|суицид\w*|самоповрежден\w*|(?:таких|этих) мыслей',text,re.I):
        full=scopes.context(m.start(),m.end())
        c=scopes.context(m.start(),m.end(),True) if re.search(r',\s*(?:(?:однако|но)\s+)?(?:вчера|сегодня|сейчас|ранее)\b',full) else full
        a,b=scopes.bounds(m.start(),m.end())
        previous=text[max(0,a-80):a].lower()
        third=scopes.third_party(m.start(),m.end())
        hist=bool(re.search(HISTORY,c))
        field='third_party_self_harm_report' if third else 'historical_self_harm_report' if hist else 'self_harm_report'
        answer=re.match(r'\s*[»”"]?\s*ответ\s*:\s*[«"]?(нет|да)\b[^.!?\n]{0,100}',text[b:b+150],re.I) if '?' in c else None
        if answer:
            s,v=('negated',False) if answer[1].lower()=='нет' else ('patient_reported',True)
            add(field,s,v,m.start(),b+answer.end())
            continue
        if scopes.uncertain(m.start(),m.end()) or 'сообщения не было' in c or '?' in c:s,v='unknown',None
        elif third:s,v='third_party',True
        elif re.search(NEGATIVE,c):s,v='negated',False
        elif hist and re.search(r'сообщал|хочу|хотел|думал|мысли|самоповрежден',c):s,v='historical',True
        elif re.search(r'сообщение пациента',c) and re.search(r'хочу|думаю|намерение|мысли',c):s,v='patient_reported',True
        elif re.search(r'сегодня|сейчас|у меня|думаю|намерение|мысли',c):s,v='present',True
        else:s,v='unknown',None
        add(field,s,v,m.start(),m.end())
    # Explicit same-sentence temporal ellipsis, anchored to a preceding report.
    # Preserve today's denial and yesterday's presence as distinct literal facts.
    for m in re.finditer(r'(?:однако|но)\s+вчера\s+(были|не было)\b',text,re.I):
        a,b=scopes.bounds(m.start(),m.end())
        prior=[c for c in candidates if c['field']=='self_harm_report' and a<=c['span']['start']<m.start() and m.start()-c['span']['end']<240]
        if prior:
            add('historical_self_harm_report','historical' if m[1].lower()=='были' else 'negated',m[1].lower()=='были',m.start(),m.end())
    for m in re.finditer(r'текущие мысли(?: пациента)? не выясняли',text,re.I):
        if any(c['field'] in ('self_harm_report','historical_self_harm_report','third_party_self_harm_report') and 0<m.start()-c['span']['end']<240 for c in candidates):
            add('self_harm_report','unknown',None,m.start(),m.end())
    for m in re.finditer(r'сегодня на этот вопрос отвечает\s*[«\"](нет|да)[»\"]',text,re.I):
        prior=[c for c in candidates if c['field'] in ('self_harm_report','historical_self_harm_report') and 0<m.start()-c['span']['end']<240]
        if prior:add('self_harm_report','negated' if m[1].lower()=='нет' else 'patient_reported',m[1].lower()!='нет',m.start(),m.end())
    scan(r'в прежней записи такого сообщения не было', 'historical_self_harm_report', fixed('unknown',None))
    scan(r'(?:сейчас жалоб нет|жалобы\s*:\s*нет)', 'current_complaints', fixed('negated',[]))
    scan(r'(?:принимаете лекарства\?\s*[—–-]\s*)?(ничего)(?=\s*[.!]|$)', 'current_medications', fixed('negated',[]),1)
    scan(r'не сообщает.{0,30}принимает ли лекарства|про собственные препараты не ответил', 'current_medications', fixed('unknown',None))
    scan(r'текущих назначений нет', 'current_prescriptions', fixed('negated',[]))
    scan(r'сопутствующ\w* лекарств нет','concomitant_medications',fixed('negated',[]))
    scan(r'другие (?:лекарства|препараты).{0,25}(?:не перечислены|список отсутствует)|полный список (?:лекарств|препаратов).{0,20}(?:не собран|будет позже)', 'concomitant_medications', fixed('unknown',None))
    scan(r'сейчас состояние не описано|состояние за эти дни неизвестны', 'current_condition', fixed('unknown',None))
    scan(r'связь с препаратом врач не оценивал|причинность не проверена', 'adverse_event_causality', fixed('unknown',None))
    scan(r'не хуже прежнего', 'sleep_change', fixed('negated','not_worse'))
    scan(r'бессонница была до начала терапии', 'insomnia_timing', fixed('historical','before_treatment'))
    scan(r'когда началось\?\s*[—–-]\s*(не помню)', 'symptom_onset', fixed('unknown',None),1)
    scan(r'\b(?:PHQ-9|GAD-7|DASS-42|DASS-21)\b', 'scale_name',lambda m:('present',m[0].upper()))
    scan(r'один ответ пропущен|не полностью', 'scale_complete',fixed('present',False))
    scan(r'версия (?:бланка )?(?:неизвестна|не обозначена)', 'scale_version',fixed('unknown',None))
    scan(r'вечерний при[её]м отмен[её]н', 'plan_change',fixed('present','evening_cancelled'))
    scan(r'вечер ещ[её] не наступил', 'adherence_evening',fixed('not_due',None))
    scan(r'утром принял назначенное|отмечен только утренний при[её]м', 'adherence_morning',fixed('patient_reported','taken'))
    scan(r'вечером пропустил', 'adherence_evening',fixed('patient_reported','missed'))
    scan(r'вчера пропустил дневной при[её]м', 'adherence',fixed('patient_reported','missed'))
    scan(r'сегодня принял утром', 'adherence',fixed('patient_reported','taken'))
    scan(r'самоотч[её]т ежедневно', 'report_schedule',fixed('present','daily'))
    scan(r'за два дня ответа нет', 'missing_report_days',fixed('present',2))

    # Different source scopes are preserved, never select one silently. Doses
    # from explicitly historical/stopped/third-party contexts are not current.
    def medication_key(candidate):
        prior=[(m,state,value) for m,state,value in meds if m.start()<=candidate['span']['start'] and state not in ('third_party','historical','stopped')]
        return prior[-1][2] if prior else None
    for field in ('age_years','dose','frequency_per_day'):
        groups={}
        for c in candidates:
            if c['field']==field and c['assertion']=='present':
                groups.setdefault(None if field=='age_years' else medication_key(c),[]).append(c)
        if field=='dose':
            scheduled={}
            for key,items in groups.items():
                timings=[re.match(r'\s*(утром|вечером|дн[её]м|на ночь)\b',text[c['span']['end']:c['span']['end']+40].lower()) for c in items]
                # Partition only when every dose has an explicit time. A bare
                # dose remains potentially conflicting, never silently resolved.
                for c,timing in zip(items,timings):
                    scheduled.setdefault((key,timing[1] if all(timings) else None),[]).append(c)
            groups=scheduled
        for items in groups.values():
            if len({json.dumps(c['value'],sort_keys=True) for c in items})>1:
                for c in items:c['assertion']='conflicting'
    for name in {v for _,_,v in meds}:
        mentions=[c for c in candidates if c['field']=='medication' and c['value']==name and c['assertion'] in ('listed','patient_reported')]
        if len(mentions)>1 and any(c['field']=='dose' and c['assertion']=='conflicting' and medication_key(c)==name for c in candidates):
            for c in mentions:c['assertion']='conflicting'
    # Repeated mentions of the same fact inside one scope are one assertion.
    merged={}
    for c in candidates:
        a,b=scopes.bounds(c['span']['start'],c['span']['end'])
        k=(c['field'],c['assertion'],json.dumps(c['value'],sort_keys=True),a,b)
        if k in merged and c['field']=='symptom':
            old=merged[k];old['span']['end']=max(old['span']['end'],c['span']['end']);old['quote']=text[old['span']['start']:old['span']['end']]
        else:merged[(k if c['field']=='symptom' else (k,c['span']['start']))]=c
    candidates=list(merged.values())
    candidates.sort(key=lambda c:(c['span']['start'],c['field']))
    for i,c in enumerate(candidates):c['id']=str(i)
    return {'version':version,'candidates':candidates,'unextracted_fields':[f for f in fields if not any(c['field']==f for c in candidates)],'warning':warning}
