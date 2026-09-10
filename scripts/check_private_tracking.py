"""Fail if private research files are tracked in the index or a chosen commit."""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.audit_publish import private_research_path


def check(ref=None):
    actual=Path(subprocess.check_output(['git','rev-parse','--show-toplevel'],cwd=ROOT,text=True).strip())
    if actual.resolve()!=ROOT.resolve():raise RuntimeError('Not the project-owned Git root')
    command=['git','ls-tree','-r','--name-only','-z',ref] if ref else ['git','ls-files','-z']
    names=[s for s in subprocess.check_output(command,cwd=ROOT).decode('utf-8').split('\0') if s]
    forbidden=[p for p in names if private_research_path(p)]
    print(json.dumps({'scope':ref or 'index','tracked_files':len(names),'private_research_files':forbidden},indent=2))
    if forbidden:raise SystemExit(1)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--ref');args=parser.parse_args();check(args.ref)
