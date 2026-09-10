"""Comparison-only corpus screening. Output is audit search space, never a review queue."""
import argparse
import json
import re
from collections import Counter
from src.audit.final50 import AUDIT, ROOT, all_raw, queues, save, now
from src.processing.category import lexical, csv_rows, stable_candidate_id
from src.processing.gen1 import stable_candidate_id as gen1_id
from src.utils.text import normalized_for_comparison

CYR = dict(zip('абвгдеёзийклмнопрстуфхцъыьэюяқғҳў',
    ['a','b','v','g','d','e','yo','z','i','y','k','l','m','n','o','p','r','s','t','u','f','x','ts','','i','','e','yu','ya','q','g','h','o']))
CYR.update({'ж':'j','ч':'ch','ш':'sh','щ':'sh','й':'y'})
def norm(t):
    t=lexical(t)
    return ''.join(CYR.get(c,c) for c in t).replace("'",'')

TARGETS={
 'GEN-1':r'\b(ayol|xotin|hotin|qiz|feminis)\w*',
 'GEN-2':r'\b(ajrash|ajrali|juvon|beva|turmush|tegmag|chiqmag|qari qiz|qiz bola)\w*',
 'GEN-3':r'\b(ayol|qiz|kiyim|ochiq|soch|hijob|romol|beti|kelin)\w*',
 'GEN-5':r'\b(erkak|xotinchalish|hotinchalish|nomard|latta|erkemas|erkemas|dayus|dayyus)\w*',
 'REG-1':r'\b(qishloq|kishlok|viloyat|kelgindi|toshkentga|toshkentni)\w*',
 'REG-2':r'\b(loli|qoraqalpoq|karakalpak|andijon|xorazm|vodiy|fargona|tojik|surxon|qashqadar|samarqand|namangan)\w*',
 'REG-3':r'\b(mankurt|manqurt|ruscha|tojikcha|ozbekcha|xorazmcha|sheva|ona tili|rus til)\w*',
 'REG-4':r'\b(migrant|gastar|musofir|rossiya|rassiya|moskva|maskva)\w*',
 'STA-1':r'\b(kambagal|qambagal|qashshoq|boyvach|boylar|boyni|pulsiz|puli yoq|otasini\w* puli|arzon kiyim)\w*',
 'STA-2':r'\b(mardikor|markidor|dehqon|dexqon|farrosh|ofitsiant|taksist|xizmatkor|quruvchi|bozorchi|qora ishchi)\w*',
 'STA-3':r'\b(jinni|jinimi|jinim|jini|ovsar|dovdir|devona|telba|nogiron|majruh|mayib|debil|imbetsil|daun|psix)\w*',
 'STA-4':r'\b(qari|kari|keksa|chol|kampir|dedushka|aqli kirmagan|yosh bola|yoshlar|yoshlig|yoshiz|yoshi katta|bola ekan)\w*',
 'STA-5':r'\b(savodsiz|savotsiz|savadsiz|sovodsiz|sovotsiz|savodi|savodi|oqimag|uqimag|chala savod)\w*',
 'REL-1':r'\b(vahob|vahhob|vaxob|vaxxob|aqidaparast|ekstrem|radikal|terror|soqol|hijob)\w*',
 'REL-2':r'\b(kofir|kafir|dahriy|daxriy|murtad|gumroh|dinsiz|dinini sot|jahannam|jahannom|yopin|namoz oqima|nomoz oqima)\w*',
}
HARM=r'\b(ahmoq|axmoq|aqlsiz|aql|savodsiz|miyasi|uyat|sharmanda|past|harom|xarom|iflos|chumo|qoloq|madaniyat|kirmas|yoqol|ket|qul|itoat|boys|qaram|kerak|shart|qaytar|buzuq|fohisha|xoin|sotqin|mol|hayvon|latta|erkak emas|odam emas|davri ot|qadri yoq|kalla|ablah|nafrat|orqada|bilm|yaram|kulgi|bilmay|la[ny]nat)\w*'
DIRECT={
 'STA-3':r'\b(jinni|jinimi|jinim|ovsar|dovdir|telba|debil|imbetsil)\w*',
 'STA-5':r'\b(savodsiz|savotsiz|savadsiz|sovodsiz|sovotsiz)\w*',
 'REL-2':r'\b(kofir|murtad|dahriy|dinsiz|jahannam|jahannom)\w*',
 'GEN-5':r'\b(erkak emas|erkemas|xotinchalish|hotinchalish|nomard|dayus|dayyus)\w*',
}

def screen():
    raw,_=all_raw(); active=queues()
    counts={}; result={}
    for cat,pat in TARGETS.items():
        rx=re.compile(pat); hr=re.compile(HARM); direct=re.compile(DIRECT.get(cat,r'(?!)'))
        known={norm(r['Example']) for r in active[cat]}
        for p in (ROOT/'data/candidates').glob(cat+'*quality_excluded.csv'):
            known.update(norm(r['Example']) for r in csv_rows(p))
        seen=set(); hits=[]
        for rid,r in raw.items():
            text=r.get('original_text') or ''; n=norm(text)
            if n in seen or n in known: continue
            match=rx.search(n)
            if not match: continue
            seen.add(n)
            harms=set(hr.findall(n))
            score=2+min(len(harms),4)*2+4*bool(direct.search(n))
            if len(text)>1200: score-=4
            if 12<=len(text)<=400: score+=1
            hits.append({'raw_id':rid,'category':cat,'candidate_id':gen1_id(normalized_for_comparison(text)) if cat=='GEN-1' else stable_candidate_id(cat,lexical(text)),
                'text':text,'source_url':r.get('source_url'),'source_title':r.get('source_identity_title') or r.get('source_name'),
                'score':score,'screen_target':match.group(),'search_space_only':True})
        hits.sort(key=lambda r:(-r['score'],len(r['text']),r['raw_id']))
        result[cat]=hits;counts[cat]=len(hits)
    save('screen.json',{'timestamp':now(),'unique_raw_screened':len(raw),'counts':counts,'categories':result})
    print(json.dumps(counts))

def screen_focused_unprocessed():
    """Only the last, previously unscreened sources; do not redo completed passes."""
    from src.utils.io import read_json
    target=AUDIT/'focused_screen.json'
    if target.exists(): raise RuntimeError('Focused extraction already exists')
    source_urls={r['url'] for r in read_json(AUDIT/'selected_sources.json')[18:]}
    raw,_=all_raw(); records={i:r for i,r in raw.items() if r['source_url'] in source_urls}
    result={c:[] for c in TARGETS}
    for c,pat in TARGETS.items():
        for rid,r in records.items():
            t=r['original_text'];n=norm(t)
            if re.search(pat,n):
                result[c].append({'raw_id':rid,'text':t,'source_url':r['source_url'],'score':len(re.findall(HARM,n)),
                    'candidate_id':gen1_id(normalized_for_comparison(t)) if c=='GEN-1' else stable_candidate_id(c,lexical(t))})
        result[c].sort(key=lambda r:(-r['score'],len(r['text'])))
    save('focused_screen.json',{'timestamp':now(),'raw_ids_screened':sorted(records),'source_urls_screened':sorted(source_urls),'categories':result})
    print(len(records),{c:len(r) for c,r in result.items()})

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--show');p.add_argument('--limit',type=int,default=35);p.add_argument('--offset',type=int,default=0)
    a=p.parse_args()
    if not a.show: screen()
    else:
        import sys;sys.stdout.reconfigure(encoding='utf-8')
        doc=json.loads((AUDIT/'screen.json').read_text(encoding='utf-8'))
        for c in a.show.split(','):
            print(c,doc['counts'][c])
            for i,r in enumerate(doc['categories'][c][a.offset:a.offset+a.limit],a.offset):
                print(i,r['raw_id'],r['candidate_id'],r['source_url'],json.dumps(r['text'],ensure_ascii=False))
