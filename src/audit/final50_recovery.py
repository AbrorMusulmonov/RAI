"""Additive, evidence-checked recovery; model suggestions never set human labels."""
import argparse
import json
from difflib import SequenceMatcher
from src.audit.final50 import AUDIT, ROOT, CATEGORIES, HUMAN, now, queues, save, all_raw, hash_file
from src.audit.final50_mine import norm
from src.processing.category import csv_rows, atomic_csv, build_row, source_verified
from src.utils.io import read_json, read_jsonl, append_jsonl
from src.processing.category import stable_candidate_id, lexical
from src.processing.gen1 import stable_candidate_id as gen1_id
from src.utils.text import normalized_for_comparison

# Indices refer only to the immutable first corpus screen. These are retrieval
# suggestions from actual full comments inspected by the coding assistant.
PICKS = {
 'GEN-1': {'PRIMARY':[18,21], 'SECONDARY':[8,9,10,13,17]},
 'GEN-2': {'PRIMARY':[1,32], 'SECONDARY':[17,21,29,30]},
 'GEN-5': {'PRIMARY':[15,16,17,18,24,27,31,33], 'SECONDARY':[4,5,19,20,21,23,29]},
 'REG-1': {'PRIMARY':[6,9], 'SECONDARY':[29,35,36]},
 'REG-2': {'PRIMARY':[0,1,31,33,35], 'SECONDARY':[25,32,34]},
 'REG-4': {'PRIMARY':[2,22], 'SECONDARY':[0]},
 'STA-2': {'PRIMARY':[5], 'SECONDARY':[]},
 'STA-3': {'PRIMARY':[1,2,4,5,6,8,9,10,11,14,16,18,27,34,45], 'SECONDARY':[0,3,13,15,17,31,39]},
 'STA-4': {'PRIMARY':[], 'SECONDARY':[82,88]},
 'STA-5': {'PRIMARY':[4,8,17,20,31,39], 'SECONDARY':[3,5,6,12,18]},
 'REL-1': {'PRIMARY':[], 'SECONDARY':[6,27,75,178]},
 'REL-2': {'PRIMARY':[5,11,13,14,25], 'SECONDARY':[4,6,9,10,12,20,24,26,35]},
}
REMOVE = {
 'STA-2':{'STA2-C-E12B7B37FD3F':'Political grievance, not worker contempt',
           'STA2-C-C1D0A7A0DE2A':'National migration lament; occupational word incidental',
           'STA2-C-250C68003128':'Family narrative; no profession-based attack'},
 'STA-4':{'STA4-C-B22309182E43':'Advocates equal access to education; not age-based abuse'},
 'REL-1':{'REL1-C-70E844050814':'Feminism/political criticism; ordinary religiosity not target',
          'REL1-C-113347E77CC4':'Opposite direction of religious policing',
          'REL1-C-9C4EC865A636':'Historical/political criticism; no ordinary-practice extremism labeling'},
}

def initialise_manifest():
    p=AUDIT/'suggestions.json'
    if p.exists(): raise RuntimeError('Suggestion manifest already exists')
    screen=read_json(AUDIT/'screen.json')
    entries=[]
    for c,tiers in PICKS.items():
        for tier,indices in tiers.items():
            for i in indices:
                r=screen['categories'][c][i]
                entries.append({'category':c,'raw_id':r['raw_id'],'candidate_id':r['candidate_id'],
                    'tier':tier,'evidence_span':r['text'],
                    'reason':'Model-assisted reading of original comment: plausible target/derogation or contextual boundary; human decision required.',
                    'stance':'POSSIBLE_ABUSE' if tier=='PRIMARY' else 'AMBIGUOUS','pass':'old_raw'})
    save('suggestions.json',{'created_at':now(),'screen_sha256':hash_file(AUDIT/'screen.json'),'suggestions':entries})

def add_screen_picks(picks, screen_name='screen.json', pass_name='old_raw'):
    """Persist only explicitly inspected raw references; supports cross-category mining."""
    doc=read_json(AUDIT/'suggestions.json'); screen=read_json(AUDIT/screen_name)
    known={(s['category'],s['raw_id']) for s in doc['suggestions']}
    for category,tiers in picks.items():
        for tier,refs in tiers.items():
            for ref in refs:
                source_cat,index=(ref[0],ref[1]) if isinstance(ref,list) else (category,ref)
                r=screen['categories'][source_cat][index]
                if (category,r['raw_id']) in known: continue
                text=r['text']; cid=gen1_id(normalized_for_comparison(text)) if category=='GEN-1' else stable_candidate_id(category,lexical(text))
                doc['suggestions'].append({'category':category,'raw_id':r['raw_id'],'candidate_id':cid,
                    'tier':tier,'evidence_span':text,'reason':'Model-assisted original-text retrieval; target and derogation/context inspected; not a human label.',
                    'stance':'POSSIBLE_ABUSE' if tier=='PRIMARY' else 'AMBIGUOUS','pass':pass_name})
                known.add((category,r['raw_id']))
    save('suggestions.json',doc)

def apply_suggestions():
    raw,_=all_raw(); registry={s['url']:s for s in read_json(ROOT/'config/sources.json')['sources']}
    manifest=read_json(AUDIT/'suggestions.json'); current=queues(); baseline=read_json(AUDIT/'baseline.json')
    logs=[]
    for c in CATEGORIES:
        # No crawling of GEN-4. A later quality audit disproved its earlier
        # readiness estimate; explicit raw-backed FN suggestions may be appended.
        rows=current[c]; old=[dict(r) for r in rows]
        excluded=csv_rows(ROOT/f'data/candidates/{c}.final50_quality_excluded.csv')
        excluded_ids={r['Candidate ID'] for r in excluded}
        for r in list(rows):
            if r['Candidate ID'] in REMOVE.get(c,{}) and r['Review Status']=='PENDING':
                rows.remove(r); excluded.append({**r,'Final50 Exclusion Reason':REMOVE[c][r['Candidate ID']]})
        known={norm(r['Example']):r['Candidate ID'] for r in rows}; ids={r['Candidate ID'] for r in rows}
        log={'category':c,'timestamp':now(),'appended_old_raw':0,'appended_new_raw':0,'skipped':[]}
        for s in manifest['suggestions']:
            if s['category']!=c or s['candidate_id'] in ids or s['candidate_id'] in excluded_ids: continue
            r=raw[s['raw_id']]; source=registry.get(r['source_url']); text=r['original_text']
            assert s['evidence_span'] and s['evidence_span'] in text, 'Invented evidence forbidden'
            if not source_verified(source) or not r.get('source_item_id'):
                log['skipped'].append({'raw_id':s['raw_id'],'reason':'SOURCE_UNVERIFIED'});continue
            if r.get('content_url') and not r.get('direct_permalink_available'):
                raise ValueError('Unsupported direct URL')
            n=norm(text)
            duplicate=known.get(n)
            if not duplicate and len(n)>=24:
                duplicate=next((v for k,v in known.items() if abs(len(k)-len(n))<=max(len(k),len(n))*.05 and SequenceMatcher(None,k,n,autojunk=False).ratio()>=.96),None)
            if duplicate:
                log['skipped'].append({'raw_id':s['raw_id'],'reason':'DUPLICATE','kept_id':duplicate});continue
            score=85 if s['tier']=='PRIMARY' else 60
            retrieval={'reason':s['reason'],'semantic_recall':True,'tier':s['tier'],'stance_hint':s['stance'],
                'stance_evidence':s['evidence_span'],'model_relevance':score/100,'model_evidence_span':s['evidence_span'],
                'compound':s.get('compound',''),'score':score,'signals':['model-assisted-original-text','exact-raw-evidence']}
            row=build_row(c,r,source,retrieval,s['candidate_id'],'PENDING','',0)
            row['Review Priority Score']=str(score);row['Final50 Raw ID']=s['raw_id'];row['Final50 Pass']=s['pass']
            rows.append(row);ids.add(row['Candidate ID']);known[n]=row['Candidate ID']
            occurrences_path=ROOT/f'data/candidates/{c}.occurrences.jsonl'
            occurrences=read_jsonl(occurrences_path)
            if not any(o.get('candidate_id')==s['candidate_id'] and o.get('raw_record_id')==s['raw_id'] for o in occurrences):
                append_jsonl(occurrences_path,[{'candidate_id':s['candidate_id'],'raw_record_id':s['raw_id'],
                    'source_url':r['source_url'],'source_item_id':r['source_item_id'],'recovery_pass':'final50'}])
            log['appended_old_raw' if s['raw_id'] in baseline['raw_ids'] else 'appended_new_raw']+=1
        for r in baseline['queues'][c]:
            if r['Review Status'] in HUMAN:
                actual=next(x for x in rows if x['Candidate ID']==r['Candidate ID'])
                assert all(actual.get(k)==v for k,v in r.items()), 'Human row changed'
        if rows!=old:
            fields=list(dict.fromkeys(k for r in old+rows for k in r))
            atomic_csv(ROOT/f'data/reviewed/{c}.review_queue.csv',fields,rows)
            # Keep active derived views synchronized to canonical human state.
            for suffix,tier in [('.csv','PRIMARY'),('.secondary_review.csv','SECONDARY')]:
                atomic_csv(ROOT/f'data/candidates/{c}{suffix}',fields,[r for r in rows if r.get('Retrieval Tier')==tier])
        if excluded:
            fields=list(dict.fromkeys(k for r in excluded for k in r))
            atomic_csv(ROOT/f'data/candidates/{c}.final50_quality_excluded.csv',fields,excluded)
        log['total']=len(rows);save(f'{c}.recovery_checkpoint.json',log);logs.append(log)
    save('last_recovery.json',logs)
    print(json.dumps(logs,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['init','apply']);a=p.parse_args()
    initialise_manifest() if a.action=='init' else apply_suggestions()
