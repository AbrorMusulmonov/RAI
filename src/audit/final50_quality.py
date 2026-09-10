"""Non-authoritative, inspectable assistant quality audit; no human labels."""
from collections import Counter
from src.audit.final50 import AUDIT,ROOT,CATEGORIES,queues,save,now,profile
from src.utils.io import read_json
from src.processing.category import csv_rows,atomic_csv

# Each index references the frozen quality_samples.json. Unlisted entries are
# genuinely ambiguous, not automatically counted as relevant. C means clear
# counter-speech; useful verbatim reported abuse is A (reviewer decides).
RATINGS={
 'GEN-1':{'PRIMARY':{'L':[0,1,4,5,7,10,11,12,13,14,15,16,17,18,19]},'SECONDARY':{'L':[1,2,6,9,11,13,15,16],'W':[0]}},
 'GEN-2':{'PRIMARY':{'L':[0,1,2,4,5,14,15],'C':[6,7,10],'W':[13]},'SECONDARY':{'L':[0,8],'C':[1]}},
 'GEN-3':{'PRIMARY':{'L':[0,1,2,3,6,7,10,11,12,14,15,16],'W':[4,8]},'SECONDARY':{'L':[1,3,7,8,16,18],'W':[4,5,10,11,12,13,14,15,17]}},
 'GEN-4':{'PRIMARY':{'L':[1,5,10,11],'C':[3],'I':[4],'W':[8]},'SECONDARY':{'L':[4,14,16],'I':[11],'C':[15],'W':[0,18]}},
 'GEN-5':{'PRIMARY':{'L':[0,1,2,3,4,5,6,9,10,11,12,13,14,15,16,17,18,19],'W':[8]},'SECONDARY':{'L':[0,1,3,4,5,7,8,11,15,18],'I':[10],'W':[12]}},
 'REG-1':{'PRIMARY':{'L':[0,1]},'SECONDARY':{'L':[4]}},
 'REG-2':{'PRIMARY':{'L':list(range(11))},'SECONDARY':{'L':[0,2,3,4,5,7,10],'I':[8],'W':[9]}},
 'REG-3':{'PRIMARY':{'L':[2],'I':[0]},'SECONDARY':{'L':[3,5],'W':[4]}},
 'REG-4':{'PRIMARY':{'L':[1,2]},'SECONDARY':{}},
 'STA-1':{},
 'STA-2':{'PRIMARY':{'L':[1,2]},'SECONDARY':{}},
 'STA-3':{'PRIMARY':{'L':[0,3,4,5,7,14,15,16,17,18,19],'I':[2,8,9,11,12,13]},'SECONDARY':{'L':[4,5,6,7,9,12,13,19],'I':[0,3,8,11,14,17],'W':[1,2,10,16]}},
 'STA-4':{'PRIMARY':{},'SECONDARY':{'L':[1,4]}},
 'STA-5':{'PRIMARY':{'L':[0,1,3,4,5,8,9,10,11,12,13,14,15],'C':[6]},'SECONDARY':{'L':[1,3,7,17,18,19],'I':[4,8,9,10,11],'C':[15]}},
 'REL-1':{'PRIMARY':{},'SECONDARY':{'W':[6]}},
 'REL-2':{'PRIMARY':{'L':[0,1,2,3,5,6,7,8,9,10,11]},'SECONDARY':{'L':[0,1,4,9,10,12,13,14,15,16]}},
}
LIMITATIONS={
 'GEN-1':'Subordination/obedience dominates; women leadership and politics still sparse; human rejects already exist.',
 'GEN-2':'Many divorce comments support women or report abuse; direct marital-status stigma sparse.',
 'GEN-3':'Prior recall admitted family disputes and generic insults without appearance/visibility; filtered sampled noise.',
 'GEN-4':'Many quotes and first-person accounts rather than direct endorsement; readiness sensitive to human treatment of reported abuse.',
 'GEN-5':'Strong masculinity-denial language; ambiguous dayus/nomard occurrences and source concentration require review.',
 'REG-1':'News/policy and counter-speech dominate; entertainment title contamination avoided; few direct origin attacks.',
 'REG-2':'Useful ethnic stereotyping but source concentration and sparse regional contexts remain.',
 'REG-3':'Neutral language policy/dialect appreciation dominate; only few actual speech-based attacks.',
 'REG-4':'Most migration comments express sympathy or policy criticism, not migrant contempt.',
 'STA-1':'Few poverty-defect attacks; reverse wealthy contempt recovered; many financial narratives and scripted source titles.',
 'STA-2':'Profession mentions overwhelmingly neutral, supportive or about national migration grievances.',
 'STA-3':'Previous psix prefix contaminated pool with psychologist praise; generic insult usage retained, clinical mentions excluded.',
 'STA-4':'Very low direct age contempt; most useful additions compound with marital status.',
 'STA-5':'Singer/title debate concentrated; quoted labeling, self-description and praise are not standalone abuse.',
 'REL-1':'Personal extremism labels often lack the parent thread showing ordinary religiosity; many entries remain ambiguous.',
 'REL-2':'Doctrinal claims and ordinary belief discussion cannot substitute for people-directed condemnation.',
}

def audit():
    samples=read_json(AUDIT/'quality_samples.json');q=queues();ratings=[];assessments={}
    extra_path=AUDIT/'quality_supplemental.json'
    extra=read_json(extra_path) if extra_path.exists() else []
    for c,tiers in samples.items():
        reviewed=[]
        for tier,rows in tiers.items():
            groups=RATINGS[c].get(tier,{})
            for i,r in enumerate(rows):
                tags=[tag for tag,indices in groups.items() if i in indices];assert len(tags)<=1
                tag=tags[0] if tags else 'A'
                entry={'category':c,'candidate_id':r['Candidate ID'],'sample_tier':tier,'audit_rating':tag,
                    'meaning':{'L':'Likely Relevant','A':'Ambiguous / potentially useful reported abuse','I':'Likely Irrelevant','C':'Counter-Speech','W':'Wrong Category'}[tag],
                    'original_example':r['Example'],'human_review_status_unchanged':'PENDING'}
                reviewed.append(entry);ratings.append(entry)
        reviewed.extend(r for r in extra if r['category']==c)
        ratings.extend(r for r in extra if r['category']==c)
        assert len({r['candidate_id'] for r in reviewed})==len(reviewed)
        current_ids={r['Candidate ID'] for r in q[c] if r['Review Status']=='PENDING'}
        current_sample=[r for r in reviewed if r['candidate_id'] in current_ids]
        weighted=0;pending_count=0;tier_estimates={}
        for tier in ('PRIMARY','SECONDARY'):
            inspected=[r for r in current_sample if r['sample_tier']==tier]
            count=sum(r['Review Status']=='PENDING' and r.get('Retrieval Tier')==tier for r in q[c])
            rate=sum(1 if r['audit_rating']=='L' else .5 if r['audit_rating']=='A' else 0 for r in inspected)/max(1,len(inspected))
            tier_estimates[tier]={'pending':count,'inspected_retained':len(inspected),'estimated_precision':rate}
            weighted+=count*rate;pending_count+=count
        precision=weighted/max(1,pending_count)
        assessments[c]={'estimated_precision':round(precision,4),
            'basis':'Assistant inspection of frozen PENDING samples plus recorded follow-up inspection, weighted by current tier counts; L=1, ambiguous/useful quoted=0.5, noise=0. Retained-sample heuristic is optimistic after known-noise removal, not a calibrated acceptance probability or independent evaluation.',
            'tier_estimates':tier_estimates,
            'sample_size':len(current_sample),'sample_counts':dict(Counter(r['audit_rating'] for r in current_sample)),
            'limitation':LIMITATIONS[c],'attempts_complete':False}
    save('quality_ratings.json',{'timestamp':now(),'ratings':ratings,'legend':'Non-authoritative assistant retrieval audit; never human annotation.'})
    save('assessments.json',assessments)

def cleanup():
    ratings=read_json(AUDIT/'quality_ratings.json')['ratings'];q=queues();log=[]
    for c,rows in q.items():
        remove={r['candidate_id']:r for r in ratings if r['category']==c and r['audit_rating'] in ('I','C','W')}
        removed=[r for r in rows if r['Review Status']=='PENDING' and r['Candidate ID'] in remove]
        if not removed:continue
        prior=csv_rows(ROOT/f'data/candidates/{c}.final50_quality_excluded.csv')
        seen={r['Candidate ID'] for r in prior}
        prior.extend({**r,'Final50 Exclusion Reason':remove[r['Candidate ID']]['meaning']+'; exact inspected sample preserved in quality_ratings.json'} for r in removed if r['Candidate ID'] not in seen)
        kept=[r for r in rows if r not in removed];fields=list(dict.fromkeys(k for r in rows for k in r))
        atomic_csv(ROOT/f'data/candidates/{c}.final50_quality_excluded.csv',list(dict.fromkeys(k for r in prior for k in r)),prior)
        atomic_csv(ROOT/f'data/reviewed/{c}.review_queue.csv',fields,kept)
        for suffix,tier in [('.csv','PRIMARY'),('.secondary_review.csv','SECONDARY')]:
            atomic_csv(ROOT/f'data/candidates/{c}{suffix}',fields,[r for r in kept if r.get('Retrieval Tier')==tier])
        log.append({'category':c,'removed_pending_ids':[r['Candidate ID'] for r in removed]})
    save('quality_cleanup.json',log)
    # Preserve both pre-cleanup and retained-sample estimates.
    if not (AUDIT/'assessments_before_cleanup.json').exists():save('assessments_before_cleanup.json',read_json(AUDIT/'assessments.json'))
    audit()

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('action',choices=['audit','cleanup']);a=p.parse_args()
    audit() if a.action=='audit' else cleanup()
