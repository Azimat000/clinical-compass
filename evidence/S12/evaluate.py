"""Frozen exact matching evaluation; never trains or writes source/data."""
from pathlib import Path
import collections
import hashlib
import json
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from apps.compass import extraction

ROOT=Path(__file__).resolve().parents[2]

def key(f):
    return f['field'],f['assertion'],json.dumps(f['value'],ensure_ascii=False,sort_keys=True)

def score(counts):
    tp,fp,fn=counts['tp'],counts['fp'],counts['fn']
    return {'tp':tp,'fp':fp,'fn':fn,'precision':tp/(tp+fp) if tp+fp else None,
            'recall':tp/(tp+fn) if tp+fn else None}

def evaluate(split):
    path=ROOT/f'data/synthetic/extraction-{split}.json'
    data=json.loads(path.read_text())
    fields=collections.defaultdict(collections.Counter)
    templates=collections.defaultdict(collections.Counter)
    records=[]
    for r in data['records']:
        result=extraction.extract(r['text'])
        all_predictions=result['candidates']
        valid_spans=all(c['quote']==r['text'][c['span']['start']:c['span']['end']] for c in all_predictions)
        if not valid_spans:
            raise RuntimeError('Fabricated quote or invalid span')
        predictions=[c for c in all_predictions if c['field'] in r['target_fields']]
        unmatched=list(predictions)
        matched=[]
        missing=[]
        counts=collections.Counter(tp=0,fp=0,fn=0)
        for gold in r['facts']:
            match=next((p for p in unmatched if key(p)==key(gold) and
                        p['span']['start']<gold['span']['end'] and gold['span']['start']<p['span']['end']),None)
            if match is None:
                fields[gold['field']]['fn']+=1
                counts['fn']+=1
                missing.append(gold)
            else:
                unmatched.remove(match)
                fields[gold['field']]['tp']+=1
                counts['tp']+=1
                matched.append({'gold_id':gold['id'],'candidate_id':match['id']})
        for p in unmatched:
            fields[p['field']]['fp']+=1
            counts['fp']+=1
        templates[r['template']].update(counts)
        critical_missing=[]
        for field in r['critical_missing_fields']:
            candidates=[p for p in all_predictions if p['field']==field]
            critical_missing.append({'field':field,'explicitly_unextracted':field in result['unextracted_fields'],
                                     'predictions':candidates,'asserted_known':any(c['assertion'] not in ('unknown','invalid','incomplete','conflicting') for c in candidates)})
        risk_fields={'age_years','dose','frequency_per_day','medication','medication_allergy','pregnancy_status','lactation_status','self_harm_report','third_party_self_harm_report','historical_self_harm_report','dyspnea'}
        records.append({'id':r['id'],'profile_id':r['profile_id'],'template':r['template'],
                        'metrics':score(counts),'prediction_count_all_fields':len(all_predictions),
                        'all_prediction_spans_valid':valid_spans,'empty_extraction':not all_predictions,
                        'matches':matched,'false_positives':unmatched,'false_negatives':missing,
                        'risk_field_false_negatives':[f for f in missing if f['field'] in risk_fields],
                        'critical_missing_fields':critical_missing,
                        'unsupported_target_fields':[f for f in r['target_fields'] if f not in extraction.FIELDS]})
    total=collections.Counter(tp=0,fp=0,fn=0)
    for values in fields.values():
        total.update(values)
    return {'split':split,'dataset_version':data['dataset_version'],'dataset_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'records':records,'micro':score(total),'per_field':{f:score(collections.Counter(tp=0,fp=0,fn=0)+v) for f,v in sorted(fields.items())},
            'per_template':{f:score(v) for f,v in sorted(templates.items())},
            'risk_field_false_negative_count':sum(len(r['risk_field_false_negatives']) for r in records),
            'critical_missing_asserted_known_count':sum(c['asserted_known'] for r in records for c in r['critical_missing_fields']),
            'empty_extraction_count':sum(r['empty_extraction'] for r in records)}

if __name__=='__main__':
    splits=sys.argv[1:] or ['development','holdout']
    report={'extractor_version':extraction.VERSION,'extractor_sha256':hashlib.sha256(Path(extraction.__file__).read_bytes()).hexdigest(),
            'scope':'Synthetic technical evaluation, not external blind or clinical validation',
            'matching':'field + assertion + normalized value + overlapping source spans; one-to-one; all gold target fields including unsupported; micro exact precision/recall',
            'splits':[evaluate(s) for s in splits]}
    print(json.dumps(report,ensure_ascii=False,indent=2))
