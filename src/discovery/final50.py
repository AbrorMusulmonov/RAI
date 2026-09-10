"""Bounded continuation discovery and collection, with honest per-attempt logs."""
import argparse
import json
from concurrent.futures import ThreadPoolExecutor
import yt_dlp
from src.audit.final50 import AUDIT, ROOT, now, all_raw, save
from src.discovery.verify_sources import verify_source
from src.collect.__main__ import download_comments, make_record
from src.utils.io import read_json, append_jsonl, read_jsonl

QUERIES={
 'GEN-1':"ayol ishlashi erining ruxsati muhokama podcast",
 'GEN-2':"ajrashgan ayol jamiyat munosabati intervyu",
 'GEN-3':"ayollar kiyinish madaniyati ochiq kiyim muhokama",
 'GEN-5':"erkak masuliyati oilada xotin puli podcast",
 'REG-1':"Toshkent viloyatliklar metro madaniyat muhokama",
 'REG-2':"lo'lilar jamiyat munosabati intervyu",
 'REG-3':"ozbekcha bilmaydigan ruscha gapiradigan ozbeklar mankurt",
 'REG-4':"Rossiyada ozbek migrantlar sharmanda hodisa munosabat",
 'STA-1':"kambagallik aybmi boy kambagal jamiyat intervyu",
 'STA-2':"mardikor bozori ayollar intervyu haqorat",
 'STA-3':"jinni ruhiy kasallik stigma ozbek podcast",
 'STA-4':"yosh rahbar qari rahbarlar muhokama",
 'STA-5':"savodsiz chala savod talim tanqid ozbek",
 'REL-1':"soqol hijob vahobiy taqiq munosabat",
 'REL-2':"ateist dinsiz ozbek bahs intervyu",
}
FOCUSED={
 'REG-1':"Toshkentlik viloyatlik",
 'REG-3':"ruscha gapirgan amaldor",
 'STA-1':"boy kambagal suhbat",
 'STA-4':"yosh rahbarlar",
 'STA-2':"mardikorlar haqorat",
 'REL-1':"soqol taqiq Ozodlik",
}

def search_one(item):
    c,q=item
    try:
        with yt_dlp.YoutubeDL({'quiet':True,'extract_flat':True,'skip_download':True,'playlistend':4,
                'ignoreerrors':True,'socket_timeout':15,'retries':0,'extractor_retries':0}) as y:
            data=y.extract_info('ytsearch4:'+q,download=False)
        results=[{k:r.get(k) for k in ('id','title','url','channel','duration')} for r in (data or {}).get('entries',[]) if r and r.get('url')]
        return {'timestamp':now(),'category':c,'query':q,'results':results,'error':None}
    except Exception as e: return {'timestamp':now(),'category':c,'query':q,'results':[],'error':str(e)}

def discover(pass_name):
    path=AUDIT/f'discovery_{pass_name}.json'
    if path.exists(): raise RuntimeError('Completed discovery exists; do not repeat blindly')
    queries=QUERIES if pass_name=='targeted' else FOCUSED if pass_name=='focused' else read_json(AUDIT/'observed_queries.json')
    rows=[]
    with ThreadPoolExecutor(max_workers=3) as pool:
        for r in pool.map(search_one,queries.items()):
            rows.append(r);save(path.name,rows)
            print(r['category'],len(r['results']),r['error'],flush=True)

def collect():
    selected=read_json(AUDIT/'selected_sources.json')
    registry=read_json(ROOT/'config/sources.json'); byurl={s['url']:s for s in registry['sources']}
    raw,_=all_raw(); crawled={r['source_url'] for r in raw.values()}
    discoveries=[]
    for p in AUDIT.glob('discovery_*.json'): discoveries.extend(read_json(p))
    found={r['url']:r for attempt in discoveries for r in attempt['results']}
    logpath=ROOT/'data/logs/final50_collection.jsonl'
    done={r['url'] for r in read_jsonl(logpath)}
    for choice in selected:
        url=choice['url'];cats=choice['categories']
        assert 'GEN-4' not in cats
        if url in done: continue
        if url in crawled:
            append_jsonl(logpath,[{'timestamp':now(),'url':url,'categories':cats,'skipped':'already in raw corpus','new_raw':0}]);continue
        e=found[url]  # Only URLs actually returned by platform search are allowed.
        source={'source_id':'YT-'+e['id'],'name':e['title'],'url':url,'platform':'YouTube','public_access':True,
            'collection_enabled':True,'likely_taxonomy_categories':cats,'discovery_pass':'final50',
            'notes':'Source-topic relevance does not qualify comments for review.'}
        verification=verify_source(source,15,now());source.update(verification)
        iv=verification['identity_verification']; reachable=verification['reachability']['reachable']
        source.update(reachability_verified=reachable,identity_verified=iv['verified'],verified=bool(reachable and iv['verified']),
            verified_title=iv.get('observed_title',''),verified_publisher=iv.get('observed_publisher',''),verified_at=now())
        log={'timestamp':now(),'url':url,'categories':cats,'verification':verification,'new_raw':0}
        if source['verified']:
            if url not in byurl:
                registry['sources'].append(source);byurl[url]=source
                (ROOT/'config/sources.json').write_text(json.dumps(registry,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            comments,error=download_comments(url,160,55)
            log['returned']=len(comments);log['error']=error
            if not error:
                # One physical occurrence, entire corpus available across categories.
                c=cats[0];records=[make_record(source,c,x,now()) for x in comments]
                records=[r for r in records if r and r['raw_record_id'] not in raw]
                log['new_raw']=append_jsonl(ROOT/f'data/raw/youtube/{c}.jsonl',records)
                raw.update({r['raw_record_id']:r for r in records})
        append_jsonl(logpath,[log]);done.add(url)
        print(cats,url,'NEW',log['new_raw'],log.get('error'),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['targeted','observed','focused','collect']);a=p.parse_args()
    collect() if a.action=='collect' else discover(a.action)
