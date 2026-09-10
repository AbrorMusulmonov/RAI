import hashlib
import json
import re
from pathlib import Path
from src.audit.final50 import ROOT,queues


def test_published_evidence_covers_every_active_review_row():
    paths=[p for p in (ROOT/'data/raw').rglob('*.jsonl')
           if p.name!='REL-1.jsonl' and not p.name.endswith('.provenance.jsonl')]
    paths.append(ROOT/'data/publication/REL-1.public.jsonl')
    evidence=set()
    for p in paths:
        for line in p.read_text(encoding='utf-8').splitlines():
            if line.strip():
                r=json.loads(line);evidence.add((r['source_url'],r['source_item_id'],r['original_text']))
    for rows in queues().values():
        for r in rows:assert (r['Source URL'],r['Source Item ID'],r['Example']) in evidence


def test_public_supplement_has_no_financial_or_contact_identifier():
    from scripts.audit_publish import FINANCIAL,PHONE
    manifest=json.loads((ROOT/'data/publication/manifest.json').read_text(encoding='utf-8'))
    payload=(ROOT/manifest['publication_file']).read_bytes()
    assert hashlib.sha256(payload).hexdigest()==manifest['publication_sha256']
    assert len(payload.splitlines())==manifest['published_records']
    assert manifest['withheld_records']==1
    for line in payload.splitlines():
        r=json.loads(line);assert not FINANCIAL.search(r['original_text']);assert not PHONE.search(r['original_text'])


def test_prompt_sections_and_exact_byte_git_attributes():
    text=(ROOT/'PROMPTS.md').read_text(encoding='utf-8')
    assert len(re.findall(r'^## [1-9]\. ',text,re.M))==9
    assert text.count('Exact supplied attachment text. Original SHA-256:')==13
    attributes=(ROOT/'.gitattributes').read_text(encoding='utf-8')
    for line in ('*.json -text','*.jsonl -text','*.csv -text','*.xlsx binary','*.pdf binary'):
        assert line in attributes.splitlines()
