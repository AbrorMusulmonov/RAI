"""Finalize evidence-backed recovery artifacts without crawling or annotating."""
import hashlib
import json
from collections import Counter, defaultdict
from src.audit.final50 import AUDIT, ROOT, CATEGORIES, HUMAN, all_raw, queues, profile, save, now, hash_file
from src.audit.final50_recovery import PICKS, REMOVE
from src.processing.category import csv_rows, atomic_csv, source_verified
from src.utils.io import read_json, read_jsonl, append_jsonl


def finish():
    baseline=read_json(AUDIT/'baseline.json');before=read_json(AUDIT/'before.json')
    resumed=read_json(AUDIT/'resume_20260909.json');q=queues();raw,physical=all_raw()
    old_raw=set(baseline['raw_ids']);new_raw=set(raw)-old_raw
    registry=read_json(ROOT/'config/sources.json')
    sources={s['url']:s for s in registry['sources']}
    original_sources={s['url']:s for s in baseline['sources']['sources']}
    assert all(sources[url]==s for url,s in original_sources.items()), 'Prior source provenance changed'
    new_sources=set(sources)-set(original_sources)
    assert old_raw<=set(raw)
    raw_prefixes=0
    for rel,info in baseline['files'].items():
        if rel.startswith('data/raw/'):
            with (ROOT/rel).open('rb') as f:
                assert hashlib.sha256(f.read(info['size'])).hexdigest()==info['sha256'], rel
            raw_prefixes+=1
        if rel.startswith('data/rejected/') or rel=='data/exports/gap_fill_review_batch_A.xlsx':
            assert hash_file(ROOT/rel)==info['sha256'],rel
    assert read_json(ROOT/'data/reviewed/final_ids.json')==baseline['final_ids']
    assert hash_file(ROOT/'config/taxonomy.json')==baseline['taxonomy_sha256']
    discovery={};queries=[]
    for name in ('targeted','observed','focused'):
        attempts=read_json(AUDIT/f'discovery_{name}.json')
        for a in attempts:
            queries.append({'pass':name,**a})
            for r in a.get('results',[]):discovery[r['url']]=r
    assert new_sources<=set(discovery), 'New URL not returned by platform discovery'
    assert all(source_verified(sources[url]) for url in new_sources)
    assert all(raw[r]['source_url'] in discovery and raw[r].get('source_item_id') for r in new_raw)
    collected=read_jsonl(ROOT/'data/logs/final50_collection.jsonl')
    selected=read_json(AUDIT/'selected_sources.json')
    assert {s['url'] for s in selected}<={s['url'] for s in collected}
    assert sum(s['new_raw'] for s in collected)==len(new_raw)
    archive={c:csv_rows(ROOT/f'data/candidates/{c}.final50_quality_excluded.csv') for c in CATEGORIES}
    human_before=human_after=0
    evidence_categories=defaultdict(set)
    for c,rows in q.items():
        for r in rows:evidence_categories[(r['Source URL'],r['Source Item ID'],r['Example'])].add(c)
    for c,rows in q.items():
        current={r['Candidate ID']:r for r in rows};archived={r['Candidate ID'] for r in archive[c]}
        assert not set(current)&archived, 'Excluded noise restored'
        old_ids={r['Candidate ID'] for r in baseline['queues'][c]}
        assert old_ids<=set(current)|archived, 'Original candidate lost'
        for old in baseline['queues'][c]:
            if old['Review Status'] in HUMAN:
                human_before+=1
                assert all(current[old['Candidate ID']].get(k)==v for k,v in old.items())
        human_after+=sum(r['Review Status'] in HUMAN for r in rows)
        path=ROOT/f'data/candidates/{c}.occurrences.jsonl'
        known={(o.get('candidate_id'),o.get('raw_record_id')) for o in read_jsonl(path)}
        added=[];changed=False
        for r in rows:
            if r['Review Status']=='PENDING' and not r.get('Human-readable Provenance'):
                r['Human-readable Provenance']=f"{r['Source Name']} | {r['Source URL']} | Source Item ID: {r['Source Item ID']}"
                changed=True
            if r['Candidate ID'] in old_ids:continue
            assert r['Review Status']=='PENDING'
            raw_id=r['Final50 Raw ID'];e=raw[raw_id]
            assert (r['Source URL'],r['Source Item ID'],r['Example'])==(e['source_url'],e['source_item_id'],e['original_text'])
            assert not r.get('Model Evidence Span') or r['Model Evidence Span'] in e['original_text']
            if (r['Candidate ID'],raw_id) not in known:
                added.append({'candidate_id':r['Candidate ID'],'raw_record_id':raw_id,
                    'source_url':e['source_url'],'source_item_id':e['source_item_id'],'recovery_pass':'final50-backfill'})
            compound=', '.join(sorted(evidence_categories[(r['Source URL'],r['Source Item ID'],r['Example'])]-{c}))
            if compound and r.get('Possible Compound Category')!=compound:
                r['Possible Compound Category']=compound;changed=True
        if added:append_jsonl(path,added)
        if changed:
            fields=list(dict.fromkeys(k for r in rows for k in r))
            atomic_csv(ROOT/f'data/reviewed/{c}.review_queue.csv',fields,rows)
            for suffix,tier in [('.csv','PRIMARY'),('.secondary_review.csv','SECONDARY')]:
                atomic_csv(ROOT/f'data/candidates/{c}{suffix}',fields,[r for r in rows if r.get('Retrieval Tier')==tier])
        assert set(REMOVE.get(c,{}))<=archived
    assert human_before==human_after==35
    screen=read_json(AUDIT/'screen.json');first98=[]
    for c,tiers in PICKS.items():
        for indices in tiers.values():
            for i in indices:first98.append((c,screen['categories'][c][i]['candidate_id']))
    preserved98=Counter()
    for c,cid in first98:
        where='active' if any(r['Candidate ID']==cid for r in q[c]) else 'quality_audit'
        assert where=='active' or any(r['Candidate ID']==cid for r in archive[c])
        preserved98[where]+=1
    search=read_json(ROOT/'config/search_terms.json')
    expansion=read_json(ROOT/'config/final50_expansion.json');observed=[]
    for c,e in expansion.items():
        r=screen['categories'][e['screen_category']][e['index']];real=raw[r['raw_id']]
        assert e['phrase'] in real['original_text']
        record={'phrase':e['phrase'],'raw_record_id':r['raw_id'],'source_url':real['source_url'],
                'source_item_id':real['source_item_id'],'query':e['query'],'phase':'final50'}
        bank=search['categories'][c].setdefault('final50_observed_phrase_evidence',[])
        if record not in bank:bank.append(record)
        phrases=search['categories'][c].setdefault('observed_real_world_phrases',[])
        if e['phrase'] not in phrases:phrases.append(e['phrase'])
        observed.append({'category':c,**record})
    (ROOT/'config/search_terms.json').write_text(json.dumps(search,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    save('observed_phrase_evidence.json',observed)
    assessments=read_json(AUDIT/'assessments.json')
    for c,a in assessments.items():
        a['attempts_complete']=True;a['checkpoint']=now()
        a['last_pass']='Final50 original-corpus screen, targeted and observed discovery, completed selected collection, FP/FN audit'
        if c=='GEN-4':a['last_pass']='No new collection: prior readiness re-audited; targeted old-raw false-negative check completed'
    save('assessments.json',assessments)
    matrix=profile();assert not any(r['Provenance Failures'] for r in matrix.values())
    counts={};contributions=[]
    for c,rows in q.items():
        initial={r['Candidate ID'] for r in baseline['queues'][c]}
        additions=[r for r in rows if r['Candidate ID'] not in initial]
        attempts=[s for s in collected if c in s['categories']]
        count={'starting_active':before[c]['Total Review'],'starting_expected_yield':before[c]['Estimated Accepted Yield'],
            'starting_gap':before[c]['Gap to 50'],'resume_active':resumed['categories'][c]['Total Review'],
            'sources_processed':len(attempts),'new_sources_attempted':sum(not s.get('skipped') for s in attempts),
            'new_verified_sources':sum(s['url'] in new_sources for s in attempts),
            'new_raw_physical':len(physical[c])-before[c]['Raw Records'],
            'old_raw_candidates':sum(r['Final50 Raw ID'] in old_raw for r in additions),
            'new_collection_candidates':sum(r['Final50 Raw ID'] in new_raw for r in additions),
            'excluded_pending':len(archive[c]),'direct_permalinks':sum(bool(r.get('Content URL')) for r in rows),
            'source_url_and_item_id_only':sum(not r.get('Content URL') for r in rows),**matrix[c]}
        counts[c]=count;save(f'{c}.final_checkpoint.json',count)
        for url,n in Counter(r['Source URL'] for r in rows).most_common():
            contributions.append({'Category':c,'Source URL':url,'Source Name':sources[url]['name'],
                'Active Candidates':n,'Share':n/len(rows),'Verified Identity':source_verified(sources[url])})
    atomic_csv(AUDIT/'candidate_count_per_source.csv',list(contributions[0]),contributions)
    totals={'timestamp':now(),'baseline_raw_records':baseline['raw_physical'],'total_raw_records':sum(map(len,physical.values())),
        'total_unique_raw_records':len(raw),'old_raw_records_screened':baseline['raw_unique'],
        'new_real_comments_collected':len(new_raw),'new_comments_after_latest_resume':len(new_raw)-resumed['new_raw'],
        'selected_sources_processed':len(collected),'old_sources_skipped':sum(bool(s.get('skipped')) for s in collected),
        'new_verified_sources':len(new_sources),'sources_returning_new_comments':sum(s['new_raw']>0 for s in collected),
        'new_candidates_from_old_raw':sum(r['old_raw_candidates'] for r in counts.values()),
        'new_candidates_from_collection':sum(r['new_collection_candidates'] for r in counts.values()),
        'baseline_active':sum(len(r) for r in baseline['queues'].values()),
        'resume_active':sum(r['Total Review'] for r in resumed['categories'].values()),
        'total_active':sum(map(len,q.values())),'statuses':dict(Counter(r['Review Status'] for rs in q.values() for r in rs)),
        'distinct_sources':len({r['Source URL'] for rs in q.values() for r in rs}),
        'recovered_98_preservation':dict(preserved98),'previous_7_exclusions_preserved':sum(map(len,REMOVE.values())),
        'total_pending_retained_in_final50_exclusion_audit':sum(map(len,archive.values())),
        'human_decisions_before':human_before,'human_decisions_after':human_after,'raw_prefix_hashes_verified':raw_prefixes,
        'synthetic_examples_created':0,'fabricated_urls_created':0,'fabricated_source_ids_created':0,
        'new_candidates_auto_accepted':0,'original_comments_rewritten':0,'human_decisions_overwritten':0,'provenance_failures':0,
        'direct_permalinks':sum(r['direct_permalinks'] for r in counts.values()),
        'source_url_and_item_id_only':sum(r['source_url_and_item_id_only'] for r in counts.values()),
        'tests':'See final50/test_results.json; full regression run required after export'}
    save('final.json',{'totals':totals,'categories':counts,'queries':queries})
    report=['# Final50 resumed recovery — evidence and limitations','',
        '## Resume','',
        f"The original immutable baseline had {totals['baseline_active']} active rows. At the latest resume checkpoint, {totals['resume_active']} rows and all 25 completed source-list entries already existed. Collection and discovery were not repeated. Remaining work resumed at candidate extraction, false-positive/false-negative auditing, occurrence backfill and Excel validation. Batch A was not rerun.",
        '', '## Interpretation','',
        'These are real, traceable candidates, not human annotations. Estimated yield = existing HUMAN ACCEPT + PENDING × an assistant retrieval estimate. The heuristic assigns likely relevance 1 and genuine ambiguity/reported abuse 0.5, weighted by PRIMARY/SECONDARY workload. Estimates use retained inspected samples, so are optimistic after known-noise removal, not calibrated probabilities. GEN-1 is borderline at approximately 50; GEN-4 depends heavily on how a human treats quoted/reported abuse. Readiness is provisional and does not mean 50 accepted examples exist.',
        '', 'SHORTFALL_DOCUMENTED means the bounded accessed corpus and completed targeted attempts did not produce enough useful evidence; it does not prove that the public web contains no more examples. Uninspected screen results are not candidates. Ten high-scoring excluded short records per category were inspected, plus a 23-record GEN-4 check; this is not an exhaustive recall estimate.',
        '', '## Preservation and totals','', '```json', json.dumps(totals,ensure_ascii=False,indent=2),'```','',
        '## Category checkpoints','']
    for c,r in counts.items():
        report.extend([f'### {c}','',
            f"Start: raw {before[c]['Raw Records']}; PRIMARY {before[c]['Primary']}; SECONDARY {before[c]['Secondary']}; active {r['starting_active']}; expected yield {r['starting_expected_yield']}; expected gap {r['starting_gap']}; human ACCEPT {before[c]['Human ACCEPT']}. Latest-resume active: {r['resume_active']}.",
            f"Recovery: {r['new_sources_attempted']} new-source collection attempts, {r['new_verified_sources']} newly registered verified URLs; {r['new_raw_physical']} physical raw records filed here; {r['old_raw_candidates']} surviving additions from old raw; {r['new_collection_candidates']} surviving additions from new collection. A source may serve several categories; source counts must not be summed across categories. Raw records are stored once under a collection category, not assigned ground-truth labels.",
            f"After: PRIMARY {r['Primary']}; SECONDARY {r['Secondary']}; active {r['Total Review']}; ACCEPT {r['Human ACCEPT']}; PENDING {r['PENDING']}; sources {r['Distinct Sources']}; largest share {r['Largest Source Share']:.1%}; estimated precision {r['Estimated Review Precision']:.1%}; estimated yield {r['Estimated Accepted Yield']}; expected gap {r['Gap to 50']}; **{r['Readiness Status']}**.",
            f"Limitation: {r['Main Limitation']}",
            f"Top five source contributions: {json.dumps(r['Top 5 Source Contributions'],ensure_ascii=False)}",''])
    report.extend(['## What worked and what remains','',
        'GEN-5 improved substantially through contextual masculinity denial and wife-control attacks; GEN-1 gained diverse working/obedience discourse. STA-3 required extensive removal of psychologist praise before its pool became useful. Opinion-heavy relationship interviews/podcasts and religious debates produced more usable comments than neutral policy/news discussion. Some wealthy-contempt statements under dramatized material were retained only as ambiguous secondary comments, not treated as fictional examples.',
        'STA-2 remains smallest (expected yield about 2.5). REG-1, REG-3, REG-4, STA-1, STA-2, STA-4 and REL-1 remain far below 35; topic keywords mostly retrieved support, policy argument or unrelated content. REG-2, STA-5 and REL-2 also remain below the approximately 50 target. Additional access to opinion-bearing public discussions and human review are still needed, not generic bulk crawling.',
        '', 'Observed phrases and their exact raw IDs/source/item IDs are in `data/audits/final50/observed_phrase_evidence.json` and the existing search configuration. Examples that helped retrieval include `хотин кули эркаклар`, `Тошкентга кайтиб кемела`, `вотти вотти`, `chala savodlar` and `Jinni xonadagi`. Search phrases are never dataset rows.',
        '', '## Excel handoff','',
        '`data/exports/FINAL_HUMAN_REVIEW.xlsx` is the main interface: 16 category sheets plus DASHBOARD and INSTRUCTIONS, 14 columns, status dropdowns, clickable genuine source links and live status-count formulas. `top_candidates_for_review.xlsx` is an optional 30-PENDING-per-category shortlist. `data_collection.xlsx` and `aziza_accepted.xlsx` contain only the three existing human ACCEPT rows.',
        'No terminal is required for review. Edit only Review Status and Reviewer Notes. Saving Excel does not automatically change the canonical CSV queues; later synchronization uses Candidate ID. The exporter refuses to overwrite unmerged human decisions/notes. Dashboard Gap to 50 counts remaining HUMAN ACCEPT decisions; readiness CSV Gap to 50 is the expected-yield gap. Formula definitions and references are regression-tested; no claim of a native Excel GUI recalculation test is made.',
        '', 'Full query attempts, including empty/off-topic results, remain in the three discovery JSON files and final.json. Exact per-source active counts are in candidate_count_per_source.csv. Quality samples, supplemental census, exclusions, FN examples and immutable baseline remain under data/audits/final50/.', ''])
    report.extend(['## All-category grouping','',
        'Provisionally ready for approximately 50: GEN-1 (borderline), GEN-4 (reported-abuse sensitivity), GEN-5, STA-3.',
        'Estimated 35–49: GEN-3 (documented shortfall).',
        'Estimated below 35: GEN-2, REG-1, REG-2, REG-3, REG-4, STA-1, STA-2, STA-4, STA-5, REL-1, REL-2 (documented shortfalls).',
        'All 12 non-ready categories retain their actual pools and limitations; none was padded to reach a target.', ''])
    (ROOT/'docs/final50_report.md').write_text('\n'.join(report),encoding='utf-8')
    print(json.dumps(totals,indent=2))


if __name__=='__main__':finish()
