from pathlib import Path
import json
import os
import tempfile
import unittest
from luna_astra.codemap import CodeMap, parse_source, sensitive
from luna_astra.util import HarnessError

class CodeMapTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.root=self.base/'project';self.root.mkdir();self.cache=self.base/'cache'
        (self.root/'engine.py').write_text('def calculate(x):\n    return x+1\n')
        (self.root/'consumer.py').write_text('from engine import calculate\ndef run(x): return calculate(x)\n')
        (self.root/'test_engine.py').write_text('from consumer import run\ndef test_run(): assert run(1)==2\n')
        self.map=CodeMap(self.root,self.cache)
    def test_python_symbols_and_imports(self):
        idx=self.map.build();self.assertEqual(idx['edges']['consumer.py'],['engine.py'])
        self.assertEqual(idx['files']['engine.py']['symbols'][0]['name'],'calculate')
    def test_query_ranks_target(self):
        idx=self.map.build();result=self.map.select(idx,'calculate engine')
        self.assertEqual(result['selected_files'][0],'engine.py')
    def test_reverse_test_dependency(self):
        risk=self.map.risk(self.map.build(),['engine.py'],['full-contract'])
        self.assertIn('test_engine.py',risk['suggested_tests']);self.assertEqual(risk['mandatory_checks'],['full-contract'])
        self.assertFalse(risk['automatic_test_skipping'])
    def test_warm_cache_uses_content_hash(self):
        a=self.map.build();b=self.map.build();self.assertEqual(b['stats']['cache_hits'],3)
        self.assertEqual(b['stats']['parsed_files'],0);self.assertEqual(a['identity'],b['identity'])
    def test_same_mtime_size_changed_content_reparses(self):
        self.map.build();p=self.root/'engine.py';st=p.stat();p.write_text(p.read_text().replace('x+1','x+2'));os.utime(p,ns=(st.st_atime_ns,st.st_mtime_ns))
        idx=self.map.build();self.assertEqual(idx['stats']['parsed_files'],1)
    def test_deleted_file_removed(self):
        self.map.build();(self.root/'consumer.py').unlink();idx=self.map.build();self.assertNotIn('consumer.py',idx['files'])
    def test_added_file_detected(self):
        self.map.build();(self.root/'new.py').write_text('def fresh(): pass');self.assertIn('new.py',self.map.build()['files'])
    def test_project_is_not_imported(self):
        marker=self.base/'EXECUTED';(self.root/'evil.py').write_text(f'from pathlib import Path\nPath({str(marker)!r}).touch()\n')
        self.map.build();self.assertFalse(marker.exists())
    def test_literals_not_stored(self):
        (self.root/'app.py').write_text('password="MY_PRIVATE_VALUE_783415"\ndef login(): return password\n')
        self.map.build();self.assertNotIn('MY_PRIVATE_VALUE',self.map.path.read_text())
    def test_sensitive_paths_excluded(self):
        for name in ('.env.py','secrets.py','credentials.py'):(self.root/name).write_text('def hidden():pass')
        idx=self.map.build();self.assertEqual(len(idx['files']),3)
    def test_node_modules_excluded(self):
        d=self.root/'node_modules';d.mkdir();(d/'large.js').write_text('function no(){}')
        self.assertEqual(len(self.map.build()['files']),3)
    def test_symlink_file_not_read(self):
        target=self.base/'private.py';target.write_text('def hidden():pass');(self.root/'link.py').symlink_to(target)
        idx=self.map.build();self.assertNotIn('link.py',idx['files'])
    def test_symlink_directory_not_walked(self):
        d=self.base/'private';d.mkdir();(d/'private.py').write_text('def hidden():pass');(self.root/'linked').symlink_to(d,target_is_directory=True)
        self.assertEqual(len(self.map.build()['files']),3)
    def test_bad_syntax_reported(self):
        (self.root/'bad.py').write_text('def broken(:')
        idx=self.map.build();self.assertEqual(idx['stats']['parse_incomplete'],1)
        self.assertEqual(self.map.risk(idx,['engine.py'])['risk'],'broader_review')
    def test_dynamic_import_risk(self):
        (self.root/'engine.py').write_text('def calculate(x): return __import__(x)')
        r=self.map.risk(self.map.build(),['engine.py']);self.assertIn('dynamic_or_incomplete_code',r['reasons'])
    def test_missing_changed_path_requires_broad_review(self):
        r=self.map.risk(self.map.build(),['gone.py']);self.assertIn('unindexed_or_deleted_change',r['reasons'])
    def test_file_budget_is_visible(self):
        mapper=CodeMap(self.root,self.cache,max_files=1);idx=mapper.build();self.assertTrue(idx['stats']['truncated'])
    def test_byte_budget_is_visible(self):
        mapper=CodeMap(self.root,self.cache,max_total_bytes=1);self.assertTrue(mapper.build()['stats']['truncated'])
    def test_output_respects_character_budget(self):
        idx=self.map.build();out=self.map.select(idx,'calculate',max_chars=500);self.assertLessEqual(out['characters'],500)
    def test_empty_query_is_bounded(self):self.assertLess(self.map.select(self.map.build(),'')['characters'],3201)
    def test_root_and_cache_guard(self):
        with self.assertRaises(HarnessError):CodeMap(self.root,self.root/'state')
        with self.assertRaises(HarnessError):CodeMap(Path('/'),self.cache)
    def test_invalid_budget_rejected(self):
        with self.assertRaises(HarnessError):CodeMap(self.root,self.cache,max_files=0)
    def test_gitignore_exclusions(self):
        (self.root/'.gitignore').write_text('ignored/\nlocal.py\n');d=self.root/'ignored';d.mkdir();(d/'x.py').write_text('x=1');(self.root/'local.py').write_text('x=2')
        self.assertEqual(len(self.map.build()['files']),3)
    def test_ignore_negation_marked_partial(self):
        (self.root/'.gitignore').write_text('!something.py');self.assertTrue(self.map.build()['stats']['ignored_patterns_partial'])
    def test_relative_imports(self):
        d=self.root/'pkg';d.mkdir();(d/'__init__.py').write_text('');(d/'a.py').write_text('from . import b\n');(d/'b.py').write_text('def b():pass')
        self.assertIn('pkg/b.py',self.map.build()['edges']['pkg/a.py'])
    def test_js_hints_labelled(self):
        (self.root/'a.ts').write_text("import {b} from './b';\nfunction a() { return b(); }")
        (self.root/'b.ts').write_text('export function b(){ return 1; }')
        idx=self.map.build();self.assertEqual(idx['files']['a.ts']['confidence'],'lexical_hint');self.assertIn('b.ts',idx['edges']['a.ts'])
    def test_cache_corruption_rebuilds(self):
        self.map.build();self.map.path.write_text('{');self.assertEqual(self.map.build()['stats']['parsed_files'],3)

    def test_nested_ignores_respected_without_affecting_sibling(self):
        d=self.root/'a';d.mkdir();(d/'.gitignore').write_text('hidden.py\n')
        (d/'hidden.py').write_text('def secret_method(): pass')
        e=self.root/'b';e.mkdir();(e/'hidden.py').write_text('def public_method(): pass')
        idx=self.map.build();self.assertNotIn('a/hidden.py',idx['files']);self.assertIn('b/hidden.py',idx['files'])
    def test_direct_nested_repository_not_indexed(self):
        d=self.root/'another';d.mkdir();(d/'.git').mkdir();(d/'x.py').write_text('def other():pass')
        self.assertNotIn('another/x.py',self.map.build()['files'])
    def test_valid_json_wrong_cache_shape_rebuilds(self):
        from luna_astra.codemap import FORMAT
        for obj in ([],{'format':FORMAT,'root':str(self.root),'files':[]}, {'format':FORMAT,'root':str(self.root),'files':{'engine.py':{'sha256':'bad'}}}):
            self.map.path.parent.mkdir(parents=True,exist_ok=True);self.map.path.write_text(json.dumps(obj))
            self.assertEqual(self.map.build()['stats']['parsed_files'],3)
    def test_valid_hash_invalid_cache_structure_reparses(self):
        idx=self.map.build();idx['files']['engine.py']['imports']=['bad'];self.map.path.write_text(json.dumps(idx))
        self.assertEqual(self.map.build()['stats']['parsed_files'],1)
    def test_lexical_lines_preserve_comments_and_literals(self):
        info=parse_source('a.ts','/* two\nlines */\nconst x="hello";\nfunction found() {}')
        self.assertEqual(info['symbols'][0]['line'],4)
    def test_no_nonpython_literal_values_in_terms(self):
        info=parse_source('a.ps1',"# PRIVATE_COMMENT_987\n$x='PRIVATE_VALUE_987'\nfunction SafeName {}")
        self.assertNotIn('PRIVATE',json.dumps(info))
    def test_static_list_truncation_reported(self):
        text='\n'.join(f'def f{i}(): pass' for i in range(160))
        self.assertIn('truncated_static_details',parse_source('big.py',text)['warnings'])
    def test_zero_time_budget_reported(self):
        idx=self.map.build(max_seconds=0);self.assertTrue(idx['stats']['truncated'])
