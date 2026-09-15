#!/usr/bin/env python3
"""Run reproducible local software checks, with immediately persisted progress."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
import sys
import time
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

@contextmanager
def canonical_test_temp():
    """Canonical temporary paths for this test process and its children only."""
    previous_cache = tempfile.tempdir
    previous_env = {key: os.environ.get(key) for key in ('TMPDIR', 'TMP', 'TEMP')}
    try:
        directory = str(Path(tempfile.gettempdir()).resolve(strict=True))
        tempfile.tempdir = directory
        os.environ.update({key: directory for key in previous_env})
        yield
    finally:
        tempfile.tempdir = previous_cache
        for key, value in previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def fingerprint():
    files={}
    for path in sorted(ROOT.rglob('*')):
        rel=path.relative_to(ROOT)
        if '__pycache__' in rel.parts or 'validation' in rel.parts or path.suffix=='.pyc' or not path.is_file():continue
        if rel.parts[0] not in {'luna_astra','prompts','tests','evals','tools','docs','.github'} and path.name not in {'luna.py','install.py','INSTALL.cmd','CHECK.cmd','UNREGISTER.cmd','PURGE.cmd','README.md','SECURITY.md','CONTRIBUTING.md','LICENSE','CHANGELOG.md','requirements-dev.txt','.gitignore','.gitattributes'}:continue
        files[rel.as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
    return hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()

class Tee:
    def __init__(self,file):self.file=file
    def write(self,text):
        self.file.write(text);self.file.flush();sys.stdout.write(text);sys.stdout.flush()
    def flush(self):self.file.flush();sys.stdout.flush()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--pattern',default='test*.py');p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.output.exists():p.error('output exists; choose a new directory to preserve previous evidence')
    a.output.mkdir(parents=True)
    before=fingerprint();start=time.time()
    with canonical_test_temp(), (a.output/'unittest.log').open('w',encoding='utf-8') as log:
        suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern=a.pattern)
        result=unittest.TextTestRunner(stream=Tee(log),verbosity=2).run(suite)
    after=fingerprint()
    obj={'pattern':a.pattern,'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
         'skipped':len(result.skipped),'expected_failures':len(result.expectedFailures),'unexpected_successes':len(result.unexpectedSuccesses),
         'successful':result.wasSuccessful() and before==after and result.testsRun>0 and not result.skipped and not result.expectedFailures,
         'wall_seconds':time.time()-start,'started_at_unix':start,'source_before_sha256':before,
         'source_after_sha256':after,'source_unchanged':before==after,'actual_model_runs':0,
         'scope':'Local software tests. Synthetic hook events do not certify native Codex or model quality.'}
    (a.output/'result.json').write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(obj,ensure_ascii=False))
    return 0 if obj['successful'] else 1
if __name__=='__main__':raise SystemExit(main())
