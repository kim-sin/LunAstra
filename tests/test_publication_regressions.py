"""Regressions from the first hosted CI; no model calls or real user configuration."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from luna_astra.codemap import CodeMap
from luna_astra.coordination import normalized
from luna_astra.crew import fingerprint
from luna_astra.gitspace import Workspaces
from luna_astra.hooks import Hooks, identity
from luna_astra.store import Store
from luna_astra.util import HarnessError, snapshot

ROOT=Path(__file__).resolve().parents[1]

class PublicationRegressions(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name).resolve();self.root=self.base/'repo';self.root.mkdir()
        (self.root/'a.py').write_text('value = 1\n',encoding='utf-8')
        self.git('init','-q');self.git('config','user.name','Regression fixture')
        self.git('config','user.email','test@example.invalid')
        self.git('config','core.autocrlf','false')
        self.git('add','a.py');self.git('commit','-qm','fixture')
        self.spaces=Workspaces(self.base/'worktrees')
    def git(self,*args):
        return subprocess.run(['git','-C',str(self.root),*args],check=True,capture_output=True)
    def inherited_filter(self,name='example'):
        config=self.base/'inherited.gitconfig'
        for kind in ('clean','smudge'):
            subprocess.run(['git','config','--file',str(config),'filter.'+name+'.'+kind,
                            'echo forbidden > filter-executed'],check=True,capture_output=True)
        env=patch.dict(os.environ,{'GIT_CONFIG_GLOBAL':str(config),'GIT_CONFIG_NOSYSTEM':'1'})
        env.start();self.addCleanup(env.stop)
        return config
    def test_unused_inherited_filters_allow_isolation(self):
        self.inherited_filter('lfs')
        info=self.spaces.prepare('a'*32,self.root,['a.py'])
        self.assertNotEqual(Path(info['tree']),self.root)
        self.assertFalse((self.root/'filter-executed').exists())
    def test_active_inherited_filter_is_refused_before_status(self):
        self.inherited_filter()
        (self.root/'.gitattributes').write_text('a.py filter=example\n')
        with self.assertRaisesRegex(HarnessError,'active checkout filter'):
            self.spaces.prepare('a'*32,self.root,['a.py'])
        self.assertFalse((self.root/'filter-executed').exists())
    def test_new_filter_cannot_run_during_integration(self):
        self.inherited_filter()
        info=self.spaces.prepare('a'*32,self.root,['a.py'])
        tree=Path(info['tree']);(tree/'a.py').write_text('value = 2\n')
        (tree/'.gitattributes').write_text('a.py filter=example\n')
        with self.assertRaisesRegex(HarnessError,'active checkout filter'):
            self.spaces.integrate('a'*32)
        self.assertFalse((tree/'filter-executed').exists())
        self.assertEqual((self.root/'a.py').read_text(),'value = 1\n')
    def test_local_clean_filter_is_refused_before_execution(self):
        (self.root/'.gitattributes').write_text('a.py filter=example\n')
        self.git('config','filter.example.clean','echo forbidden > filter-executed')
        with self.assertRaisesRegex(HarnessError,'filters configured locally'):
            self.spaces.prepare('a'*32,self.root,['a.py'])
        self.assertFalse((self.root/'filter-executed').exists())
    def test_zero_budget_is_deterministic_with_frozen_clock(self):
        with patch('luna_astra.codemap.time.monotonic',return_value=1.0):
            result=CodeMap(self.root,self.base/'map').build(max_seconds=0)
        self.assertTrue(result['stats']['truncated'])
        self.assertEqual(result['stats']['indexed_files'],0)
    def test_noncanonical_root_fingerprint_matches(self):
        (self.root/'subdir').mkdir();alias=self.root/'subdir'/'..'
        self.assertEqual(fingerprint(alias,['a.py','future.txt']),fingerprint(self.root,['a.py','future.txt']))
        self.assertEqual(snapshot(alias,['a.py']),snapshot(self.root,['a.py']))
    def test_absolute_equivalent_scope_is_normalized(self):
        (self.root/'subdir').mkdir()
        self.assertEqual(normalized(self.root,str(self.root/'subdir'/'..'/'a.py')),'a.py')
    def test_worker_alias_keeps_original_identity(self):
        state=self.base/'state';hooks=Hooks(ROOT,state);store=Store(state)
        event={'session_id':'parent','agent_id':'child','hook_event_name':'SubagentStart',
               'model':'gpt-5.6-luna','cwd':str(self.root),'turn_id':'t'}
        hooks.handle(event);key=identity(event)[0]
        tree=self.base/'assigned';tree.mkdir();(tree/'sub').mkdir()
        meta=store.get(key,'meta');meta['assigned_workspace']=str(tree/'sub'/'..');store.put(key,'meta',meta)
        hooks.handle({**event,'session_id':'child','cwd':str(tree),'hook_event_name':'PostToolUse',
                      'tool_use_id':'u','tool_name':'read_file','tool_response':{'exit_code':0}})
        self.assertEqual(store.get(key,'meta')['last_event'],'PostToolUse')
        self.assertEqual(len(hooks.doctor()['sessions']),1)

    def test_reserved_filter_value_is_not_mistaken_for_no_filter(self):
        self.inherited_filter('unspecified')
        (self.root/'.gitattributes').write_text('a.py filter=unspecified\n')
        with self.assertRaisesRegex(HarnessError,'ambiguous checkout filter name'):
            self.spaces.prepare('a'*32,self.root,['a.py'])
        self.assertFalse((self.root/'filter-executed').exists())
