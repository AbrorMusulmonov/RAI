"""Read-only pre-publication checks; reports paths/counts, never matched secrets.

The scan is a heuristic, not a guarantee that third-party text contains no PII.
It does not rewrite research evidence, annotate examples or access the network.
"""
import argparse
import csv
import hashlib
import io
import json
import os
import re
import subprocess
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SKIP={'.git','.venv','venv','node_modules','__pycache__','.pytest_cache','.mypy_cache',
      '.ruff_cache','.cache','.dist','dist','build','.publish-local','.idea'}
PRIVATE_HOLDOUTS={'PROMPTS.md','docs/methodology.md','docs/collection_log.md',
                  'docs/final50_report.md','docs/source_strategy.md'}
PRIVATE_PREFIXES=('data/','config/','notebooks/','.publish-local/')
PRIVATE_SUFFIXES={'.pdf','.xlsx','.xls','.csv','.jsonl','.parquet','.arrow',
                  '.feather','.sqlite','.sqlite3','.db'}


def private_research_path(path):
    """Publication policy only: this never deletes or rewrites a local file."""
    rel=str(path).replace('\\','/').removeprefix('./')
    lowered=rel.lower()
    return lowered in {p.lower() for p in PRIVATE_HOLDOUTS} or lowered.startswith(PRIVATE_PREFIXES) or Path(rel).suffix.lower() in PRIVATE_SUFFIXES
SECRET_PATTERNS={
    'github_token':re.compile(r'\b(?:github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{20,})'),
    'google_api_key':re.compile(r'\bAIza[0-9A-Za-z_-]{30,}'),
    'api_key':re.compile(r'\bsk-[A-Za-z0-9_-]{20,}'),
    'aws_access_key':re.compile(r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b'),
    'private_key':re.compile(r'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----'),
    'credential_url':re.compile(r'https?://[^\s/"<>:]+:[^\s/"<>@]+@'),
}
LOCAL_PATH=re.compile(r'(?:[A-Za-z]:[\\/]+Users[\\/]+[^\s"<>]+|/(?:Users|home)/[^\s"<>]+)')
PHONE=re.compile(r'(?<!\d)(?:\+?998[\s().-]*(?:\d[\s().-]*){9}|\+7[\s().-]*(?:\d[\s().-]*){10})(?!\d)')
EMAIL=re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b')
FINANCIAL=re.compile(r'\b4[0-9]{19}\b')
PRIVATE_FIELDS={'access_token','refresh_token','api_key','api_hash','authorization','cookie','cookies',
                'phone_number','email_address','password','private_key','session_string',
                'contacts','contact_book','auth_key','browser_profile','oauth_secret'}


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def research_snapshot():
    return {p.relative_to(ROOT).as_posix():digest(p) for name in ('config','data')
            for p in (ROOT/name).rglob('*') if p.is_file()}


def private_keys(value):
    found=set()
    if isinstance(value,dict):
        for k,v in value.items():
            if str(k).lower() in PRIVATE_FIELDS and v not in (None,'',[],{}):found.add(str(k))
            found.update(private_keys(v))
    elif isinstance(value,list):
        for v in value:found.update(private_keys(v))
    return found


def scan_paths(paths):
    result={'files_scanned':0,'bytes_scanned':0,'credential_findings':[],
        'local_path_findings':[],'private_metadata_findings':[],'financial_identifier_findings':[],
        'raw_original_text_contact_patterns':[],'large_files_over_50_mib':[],
        'oversized_files_over_100_mib':[],'largest_files':[]}
    sizes=[]
    for p in paths:
        rel=p.relative_to(ROOT).as_posix();size=p.stat().st_size
        result['files_scanned']+=1;result['bytes_scanned']+=size;sizes.append((size,rel))
        if size>50*1024**2:result['large_files_over_50_mib'].append(rel)
        if size>100*1024**2:result['oversized_files_over_100_mib'].append(rel)
        suffix=p.suffix.lower()
        if suffix=='.xlsx':
            with zipfile.ZipFile(p) as z:
                text='\n'.join(z.read(n).decode('utf-8',errors='replace') for n in z.namelist() if n.endswith(('.xml','.rels')))
        elif suffix=='.pdf':
            from pypdf import PdfReader
            pdf=PdfReader(p)
            text=str(pdf.metadata)+'\n'+'\n'.join(page.extract_text() or '' for page in pdf.pages)
        elif suffix in ('.py','.json','.jsonl','.csv','.md','.txt','.ipynb','.ini','.toml','.example') or p.name.startswith('.') or p.name=='LICENSE':
            text=p.read_text(encoding='utf-8-sig',errors='replace')
        else:continue
        for kind,pattern in SECRET_PATTERNS.items():
            if pattern.search(text):result['credential_findings'].append({'path':rel,'kind':kind})
        if LOCAL_PATH.search(text):result['local_path_findings'].append(rel)
        if FINANCIAL.search(text):result['financial_identifier_findings'].append(rel)
        fields=set()
        if suffix=='.json':
            fields=private_keys(json.loads(text))
        elif suffix=='.jsonl':
            phones=emails=0
            for line in text.splitlines():
                if not line.strip():continue
                r=json.loads(line);fields.update(private_keys(r))
                if rel.startswith('data/raw/') and not rel.endswith('.provenance.jsonl'):
                    original=r.get('original_text','')
                    phones+=bool(PHONE.search(original));emails+=bool(EMAIL.search(original))
            if phones or emails:
                result['raw_original_text_contact_patterns'].append({'path':rel,'records_with_phone_pattern':phones,'records_with_email_pattern':emails})
        elif suffix=='.csv':
            reader=csv.DictReader(io.StringIO(text));headers=reader.fieldnames or []
            fields={x for x in headers if x.lower() in PRIVATE_FIELDS}
        if fields:result['private_metadata_findings'].append({'path':rel,'field_names':sorted(fields)})
    result['largest_files']=[{'path':p,'bytes':s} for s,p in sorted(sizes,reverse=True)[:10]]
    return result


def workspace_paths():
    paths=[];excluded=[]
    for parent,dirs,names in os.walk(ROOT):
        dirs[:]=[d for d in dirs if d not in SKIP]
        for name in names:
            p=Path(parent)/name
            if private_research_path(p.relative_to(ROOT).as_posix()) or (name.startswith('.env') and name!='.env.example') or name.endswith(('.bak','.zip','.log','.pyc','.tmp','.temp','.session','.pem','.key')) or name.startswith('~$'):
                excluded.append(p.relative_to(ROOT).as_posix());continue
            paths.append(p)
    return sorted(paths),excluded


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--staged',action='store_true');parser.add_argument('--snapshot',action='store_true')
    parser.add_argument('--verify-snapshot',action='store_true');args=parser.parse_args()
    local=ROOT/'.publish-local';local.mkdir(exist_ok=True)
    if args.snapshot:
        p=local/'research_before.json'
        if p.exists():raise RuntimeError('Refusing to replace preservation snapshot')
        p.write_text(json.dumps(research_snapshot(),indent=2)+'\n',encoding='utf-8')
    if args.verify_snapshot:
        old=json.loads((local/'research_before.json').read_text(encoding='utf-8'))
        current=research_snapshot()
        changed=[p for p,h in old.items() if current.get(p)!=h]
        if changed:raise RuntimeError('Research files changed: '+', '.join(changed))
        print(f'Research preservation: {len(old)} original files unchanged')
    if args.staged:
        root=subprocess.check_output(['git','rev-parse','--show-toplevel'],cwd=ROOT,text=True).strip()
        if Path(root).resolve()!=ROOT.resolve():raise RuntimeError('Refusing parent-repository index')
        names=subprocess.check_output(['git','diff','--cached','--name-only','--diff-filter=ACMR','-z'],cwd=ROOT).decode('utf-8').split('\0')
        paths=[ROOT/n for n in names if n];excluded=[]
    else:paths,excluded=workspace_paths()
    forbidden=[p.relative_to(ROOT).as_posix() for p in paths if private_research_path(p.relative_to(ROOT).as_posix())]
    if forbidden:
        print(json.dumps({'private_research_paths_blocked':forbidden},indent=2));raise SystemExit(1)
    result=scan_paths(paths);result['excluded_local_files']=excluded
    result['checked_at']=datetime.now(timezone.utc).isoformat(timespec='seconds')
    result['scope']='staged paths (working-tree bytes; index equality separately checked)' if args.staged else 'current workspace excluding generated/private paths'
    result['limitations']='Heuristic secret/PII scan; original public comments may contain self-disclosed contact strings. Matches are not automatically private metadata. No original comment is redacted or rewritten by this script.'
    out=local/('staged_audit.json' if args.staged else 'workspace_audit.json')
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=True,indent=2))
    if result['credential_findings'] or result['private_metadata_findings'] or result['financial_identifier_findings'] or result['oversized_files_over_100_mib']:raise SystemExit(1)


if __name__=='__main__':main()
