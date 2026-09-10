"""Create an additive privacy-safe evidence supplement; originals stay untouched."""
import hashlib
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.audit_publish import FINANCIAL, PHONE
from src.audit.final50 import queues


def write_once(path,payload):
    if path.exists():
        if path.read_bytes()!=payload:raise RuntimeError(f'Existing artifact differs: {path.name}')
        return
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('xb') as f:f.write(payload)


def prepare():
    source=ROOT/'data/raw/youtube/REL-1.jsonl'
    original=source.read_bytes();lines=original.splitlines(keepends=True)
    kept=[];held=[]
    active={r['Example'] for rows in queues().values() for r in rows}
    for line in lines:
        r=json.loads(line);text=r.get('original_text','')
        if FINANCIAL.search(text) or PHONE.search(text):
            assert text not in active, 'A reviewed candidate needs an explicit publication decision'
            held.append(r['raw_record_id'])
        else:kept.append(line)
    assert len(held)==1,'Unexpected privacy scope: inspect before changing the release'
    output=ROOT/'data/publication/REL-1.public.jsonl'
    payload=b''.join(kept);write_once(output,payload)
    assert source.read_bytes()==original,'Original raw changed'
    manifest={'purpose':'Additive publication evidence; not a replacement of canonical local raw.',
        'source_file':'data/raw/youtube/REL-1.jsonl',
        'source_sha256':hashlib.sha256(original).hexdigest(),
        'publication_file':'data/publication/REL-1.public.jsonl',
        'publication_sha256':hashlib.sha256(payload).hexdigest(),
        'original_records':len(lines),'published_records':len(kept),'withheld_records':len(held),
        'reason':'One unrelated public fundraising comment contains personal phone and bank details; not an active review candidate.',
        'original_comment_text_rewritten':0,
        'private_originals_retained_locally':['data/raw/youtube/REL-1.jsonl',
            'data/raw/youtube/GEN-1.provenance.jsonl','data/audits/final50/screen.json'],
        'historical_replay_limit':'Exact historical preservation tests and screen-index re-mining require the local private originals. They are deliberately not silently replaced or skipped.',
        'usage':'Use the public supplement alongside other published raw files to check current review provenance. It is outside data/raw so it cannot double-count local raw or alter existing pipeline behavior.'}
    write_once(ROOT/'data/publication/manifest.json',(json.dumps(manifest,indent=2)+'\n').encode('utf-8'))
    print(json.dumps(manifest,indent=2))


if __name__=='__main__':prepare()
